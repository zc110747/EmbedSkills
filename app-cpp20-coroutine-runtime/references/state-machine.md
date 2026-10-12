# 任务状态机 · 归属 · 竞态（完整表）

配套 `app-cpp20-coroutine-runtime/SKILL.md`。回答三个容易做错的问题：
**有哪些状态？谁在某一刻拥有协程帧？两方同时想唤醒同一个任务，谁赢？**

---

## 一、状态集合

| 状态 | 含义 |
|---|---|
| `Created` | 帧已存在，但从未交给调度器（仅 `Task::state()` 在 spawn 之前可见） |
| `Ready` | 在就绪队列里，等自己的调度轮次 |
| `Running` | 正在循环线程上执行 |
| `WaitingTimer` | 挂在 `sleep_for` / `sleep_until` |
| `WaitingEvent` | 挂在事件等待（`Event::wait()`）**或** `co_await <子任务>` |
| `WaitingChannel` | 挂在通道的 send / receive |
| `Cancelling` | 运行中收到取消请求；会继续跑到下一个检查点 |
| `Completed` | **终态**：函数体正常返回 |
| `Cancelled` | **终态**：经取消异常退出，或取消请求被受理 |
| `Failed` | **终态**：经其它未处理异常退出 |

`is_terminal(s)` 对最后三个为真；`is_waiting(s)` 对三个 `Waiting*` 为真。

### `Cancelling` 不是 fail-stop

`Cancelling` 的含义是"有请求挂起"。协程**仍在 CPU 上**，可以继续跑任意代码（包括清理），直到
它到达一个 await 点。这是"协作式取消"的协作部分，也是**取消永远不会漏资源**的原因：
帧总是正常展开，每个局部析构都会跑。

**不对称点**：一个 catch 住取消异常后正常返回的任务，终态**仍是 `Cancelled`** ——
请求已被受理，调用方不能把它误当成功。

---

## 二、转移表（"触发"指代码路径；未列出的转移不可达）

### 2.1 从 `Created`

| 到 | 触发 | 说明 |
|---|---|---|
| `Ready` | `register_task()`（经 `spawn()`，或经 awaiter 注册未 spawn 的子任务） | **先置状态再入队**，队列里永不出现"状态与队列不一致"的 id |
| `Cancelled` | 对 `Created` 任务 `cancel_impl()` → `finish_before_start()` | 防御性：调度器实际从不持有 `Created` 任务，因为 `register_task` 在同一调用里把它移到 `Ready` |

### 2.2 从 `Ready`

| 到 | 触发 | 说明 |
|---|---|---|
| `Running` | 循环派发 | 置 `started = true`；循环拒绝派发已终态的任务 |
| `Cancelled` | `started == false` 时 `cancel_impl()` → `finish_before_start()` | 函数体永不运行；循环的 `!started && cancel_requested` 守卫重复检查"请求在 id 已入队时才落地"这一情形 |
| `Ready`（不变） | `started == true` 时 `cancel_impl()` | 一个被**唤醒出等待**又被取消的任务保持 `Ready`，但置了 `wait_cancelled`，恢复时 await 点抛异常 |

### 2.3 从 `Running`

| 到 | 触发 | 说明 |
|---|---|---|
| `WaitingTimer` | `sleep_for`/`sleep_until` → `begin_wait` → 入定时器堆 | 已过期的 deadline **根本不挂起**（`await_ready` 为真）——但它**仍是取消检查点** |
| `WaitingEvent` | `Event::wait()` → `begin_wait`；或任务 join 的 `await_suspend` | 仅当事件未置位、且子任务未终态 |
| `WaitingChannel` | 通道 send/receive → `begin_wait` | 仅当操作无法同步完成 |
| `Cancelling` | 运行中 `cancel_impl()` | 协作：什么也不中断 |
| `Completed` | 无异常无请求时 `final_suspend()` | 经 `finish_task()` |
| `Cancelled` | 取消 / 取消异常退出后 `final_suspend()` | |
| `Failed` | 其它未处理异常后 `final_suspend()` | 异常存进 TCB；await 的父会重新抛出 |

### 2.4 从任一 `Waiting*` 回来

| 到 | 触发 | 说明 |
|---|---|---|
| `Running` | `abort_wait()` | awaiter 决定**不挂起**（操作在 `await_suspend` 内同步完成）。这是一次**调用内**转移：`begin_wait` 先置了等待态，`abort_wait` 再还原为 `Running` |
| `Ready` | `wake(task, gen)` 成功路径 | 定时器到期 / 事件通知 / 通道交值或腾出缓冲 |
| `Ready` | `fail_wait(task, gen, err)` 失败路径 | 错误存下、在 await 点抛出（`ChannelClosedError` / `ObjectDestroyedError`） |
| `Ready` | `cancel_impl()` → 置 `wait_cancelled` + `wake()` | await 点随后抛取消异常 |

`wake` 与 `fail_wait` 都以 `(task, generation)` 仍匹配为门槛 ⇒ 给定一次挂起，上表**恰好一行**能触发。

### 2.5 从 `Cancelling`

| 到 | 触发 |
|---|---|
| `Cancelling` | 再次 `cancel_impl()` —— 直接早退，因为请求已置位 |
| `Completed`/`Cancelled`/`Failed` | 函数体到达终态。实践中会是 `Cancelled`，因为下一个库 await 点会抛 |

### 2.6 终态

终态**没有出边**。`is_terminal()` 守卫每个写入者：`cancel_impl()` 对终态任务返回 `false`；
循环丢弃状态已终态的排队 id。

---

## 三、归属（谁拥有协程帧）

| 时刻 | 拥有者 |
|---|---|
| `Task<T> t = some_coro(...)` | `Task` 对象。帧已**急切**分配，函数体尚未运行 |
| `spawn(std::move(t))` | 调度器。`t` 变空（`t.valid() == false`） |
| `co_await t` | 当前调度器；awaiter 接管句柄，从 `await_suspend` 起该帧按普通任务调度 |
| `t` 仍持有时被销毁 | 帧被销毁。这使 `spawn(make_task())` 安全，也是"未 spawn 的任务静默什么都不做"的原因 |
| 终态 + `awaiter_refs == 0` | 入回收队列，由 `reclaim_pending()` 销毁 |
| `~Scheduler` 时仍有帧被拥有 | 析构器销毁每个存活帧 |

`Task` 是 **move-only**。移动构造只转移句柄，绝不分配/销毁帧；**移动赋值**会先销毁目标原本
拥有的帧再接管源的 —— 那是 `Task` 赋值**唯一**改变帧计数的位置（计数断言要留意）。

### TCB

TCB 是 **promise 的成员** ⇒ 活在帧里、随帧销毁。调度器只持非拥有记录。推论：

- 没有第二块要释放的内存，也不可能在帧还活着时释放 TCB；
- `alive == false` 表示"TCB 指针已悬垂" —— 所有辅助函数走 `control_of(id)`，对死记录返回
  `nullptr`，于是陈旧 id 是良性 no-op 而非 use-after-free；
- `last_state`（在 `alive = false` **之前**写入）让 `task_state(id)` 在回收之后仍有意义。

### 带挂起等待者的事件 / 通道

两者都在析构里**同步**失败每个挂起的等待者：

- 事件析构 → 每个挂起等待者收 `ObjectDestroyedError`；
- 通道析构 → 挂起的发送者与接收者都收 `ObjectDestroyedError`；
- `Channel::close()` → 挂起**发送者**收 `ChannelClosedError`；挂起**接收者**先排空缓冲再收错。

失败是**在析构里同步**发生的：给每个等待者存 `wait_error` 并移入 `Ready`。这就是"在有协程
park 在等待对象上时销毁它"是**安全且可观测**而不是未定义行为的原因。

> ⚠️ **绝不要在别的线程可能正在使用该等待对象时销毁它。** 析构只在循环线程（或循环未运行时）安全。

### `TimerHandle`

move-only RAII，是 `TimerControl` 的唯一所有者：丢弃句柄 = 取消定时器；`cancel()` 幂等且
线程安全；**移动赋值会先取消目标原本拥有的定时器**，再接管源的。被取消的定时器永不触发，
但其堆条目**惰性**消失。

---

## 四、`abort_wait` 为什么必须有

若 awaiter 发现能同步完成（有空间的通道、已置位的事件、已过的 deadline），它已经在
`begin_wait` 里改过代号与状态了。`abort_wait(task, generation)` 把状态放回 `Running`。
它在代号失配时是 no-op —— 这一点很重要，因为期间可能**真的**来了一个取消，把任务移出了等待。

---

## 五、注意（容易被当成 bug 的行为）

- **`clear_finished()` 会让过期 id 读成 `Created`。** 注册表条目丢弃后，`task_state(id)`
  无法区分"早就结束了"与"从未存在"。要在任务结束很久后仍能查它，就别清（或自己缓存终态）。
  这是**被显式断言**的行为，不是意外。
- **`run()` 返回时会清 `stop_requested`。** 所以 `run()` 之后读它是 `false` —— 这正是调度器
  可复用的原因。需要在回调**内部**断言才能观察到请求。
- **帧计数是进程级的。** 跨进程里出现过的每个调度器累加；测试里用**增量**，不要用绝对值。
- **`Created` 无法经调度器到达。** 它只为"`spawn()` 之前 `Task::state()` 有意义"而存在，
  以及作为 `finish_before_start()` 的防御性输入。
