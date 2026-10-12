# 运行时设计细节（事件循环 · 线程契约 · 不变量）

配套 `app-cpp20-coroutine-runtime/SKILL.md`。所有结论来自一个实测过的单线程协作式
C++20 协程运行时（Scheduler + `Task<T>` + Timer + Event + Channel/BlockChannel + Cancellation），
在 GCC 15.2 (MinGW-w64) 与 Clang 14 上 Debug/Release 双构零警告、ctest 全绿。

---

## 一、事件循环：一次迭代做什么，以及**为什么是这个顺序**

| # | 步骤 | 做什么 |
|---|---|---|
| 1 | `drain_external()` | 执行 `post()` / 外部线程 `cancel()` 排进来的回调 |
| 2 | `expire_timers()` | 触发所有已到期定时器，按 `(deadline, sequence)` 顺序 |
| 3 | `reclaim_pending()` | 销毁「已终态 且 无引用」的协程帧 |
| 4 | `prune_timers()` | 每 64 次迭代做一次：丢掉永远不可能触发的定时器条目 |
| 5 | 停机检查 | 若观察到 `request_stop()`，执行 `cancel_all()` |
| 6 | dispatch | 从就绪队列弹出**一个** id 并 resume |
| 7 | idle | 无就绪任务时：退出，或睡到下一个 deadline |

顺序不是随意的：

- **外部工作最先。** 外部线程的 `cancel()` 必须在循环决定跑什么**之前**落地，否则循环可能
  派发一个外面已经认为取消了的任务。
- **定时器先于派发。** 定时器只把被唤醒的任务**推入**就绪队列；本轮或下轮才被派发，
  **绝不**在定时器回调里内联执行。⇒ 想立刻观察到通知的代码，必须在发出通知**之后**挂起
  （否则它自己还没挂起，通知就丢了）。这是一个极易踩的语义点。
- **回收先于派发。** 上一轮进入终态的帧在这轮任何新工作开始前销毁，循环不会跨轮持有僵尸帧。
- **一轮只派发一个任务。** 让循环对外部请求保持响应、让回收节奏固定；代价是每次 resume 一次
  队列往返（`std::deque`）。

### 空闲：阻塞在条件变量上，不轮询

```
wait_for_work():
  无定时器  -> 等外部工作 / request_stop()
  有定时器  -> 等到最近的 deadline；期间被外部请求或"更早的定时器插入"提前唤醒
```

进程在 deadline 之间是**真正空闲**的（无自旋、无轮询间隔）。`cancel()` 一个定时器也要 notify，
否则停机会空等到那个 deadline。

### 终止

`run()` 同时满足两条才返回：

1. `active_tasks == 0` —— 没有已注册且非终态的任务；
2. 一次性回调定时器数为 0 —— 没有"还可能触发"的排队回调。

**周期性回调定时器刻意不维持循环存活**：它们是后台源，必须靠丢弃/取消其句柄（或
`request_stop()`）停掉，否则 demo 永不退出。退出前跑一次全量 `prune`，让运行后诊断
（`pending_timer_count()` / `live_timer_count()`）**精确**，而不是"每个被取消的定时器留一条垃圾
条目"。

---

## 二、任务存储：控制块放在 promise 里

```
协程帧（堆）
+-------------------------------------------+
| promise_type                              |
|   TaskControlBlock control;   <-- TCB     |
|   optional<T> value;                      |
+-------------------------------------------+
| 协程参数、局部变量、临时对象                |
+-------------------------------------------+
```

TCB 是 **promise 的成员**，不是单独分配的对象。两条推论都重要：

1. TCB 生命周期**恰好**等于帧生命周期 —— 没有第二个记账对象可泄漏或释放两次。
2. TCB **不归调度器所有**。调度器只持非拥有记录
   `TaskRecord { TaskControlBlock*, coroutine_handle<>, bool alive, TaskState last_state }`。
   `alive` 翻 `false` 后记录仍能从缓存 `last_state` 回答状态查询。

TCB 是**协程类型擦除**的：Scheduler / Event / Channel<T> / TimerHandle 全用 `TaskId` + TCB，
永远看不到 `Task<T>` 的类型参数 —— 这是"一个运行时支撑多种等待对象"的关键。

### `awaiter_refs`：让已结束的帧多活一会儿

父 `co_await child` 要在子**结束之后**读子的结果 ⇒ "子结束"不能等于"立刻销毁帧"。

```
await_suspend():              child.awaiter_refs++ ; child.continuation = parent
子进入终态(finish_task):       reclaim_when_unref = true
                              if (awaiter_refs == 0) 入回收队列
await_resume() 读值之前:       release() -> --awaiter_refs ; 归零则调度回收
兜底:                         回收一个仍设着 awaiting_child 的 TCB 时，代它释放那次引用
```

最后一条兜底很关键：没有它，一个不经过栈展开就被销毁的父帧会**永久搁浅**子的引用计数。

### 全局帧计数

`global_counters()`（进程级，非按实例）暴露 `frames_created` / `frames_destroyed` /
`tasks_created`。刻意进程级的原因：**`frames_created == frames_destroyed` 在测试二进制末尾
是一个比按实例检查强得多的断言**，而且任何按实例计数都**抓不到「帧活得比调度器还久」**。
任务计数（`tasks_completed` 等）才是按实例的。

---

## 三、等待 / 唤醒 / 竞态

统一的三调用协议：

| 调用 | 含义 |
|---|---|
| `begin_wait(task, wait_state)` | 自增 `wait_gen`、置状态（`WaitingTimer/Event/Channel`）、返回新代号 |
| `abort_wait(task, generation)` | awaiter 决定**不挂起**（同步完成）时还原状态 |
| `wake(task, generation)` | **仅当**仍在等待态**且**代号匹配时移到 `Ready` |
| `fail_wait(task, generation, error)` | 同上，但存一个 `wait_error` 在 await 点抛出 |

### 为什么用代号计数而不是锁

一个任务可以同时被多方等待。具体地，一个 park 在 `receive()` 的任务可被：
发送者推值、`close()` 失败它、`cancel(id)` 取消它、通道析构失败它（`ObjectDestroyedError`）
—— **四者可能在同一轮发生**。没有保护就有两个各自 `wake()` 同一任务 → 经典双重 resume。

代号计数在**单线程**前提下无锁解决：

1. `begin_wait` 递增 `wait_gen` ⇒ 每次注册都是**唯一**的 `(task, generation)`；
2. `wake(task, generation)` 是对该对的 CAS：第一个调用者把状态翻出等待态，后来者看到非等待态
   返回 `false`；
3. 代号过期的注册（任务已再次挂起，或已被取消并恢复）永远无法满足检查 ⇒ 陈旧定时器条目 /
   陈旧通道槽**惰性且无害**。

副作用是**陈旧处理被局部化到唤醒方**：没有任何一方去扫描定时器堆或通道等待链表来"反注册"，
也就没有双份记账可以漂移。惰性删除 + 周期性压实让定时器堆不会无界增长。

### 竞态裁决表（赢家 / 输家看到什么）

规则只有一条：**`wake`/`fail_wait` 仅当任务仍在等待且代号相同才成功；第一个调用者赢。**

| 竞态 | 赢家 | 输家看到 |
|---|---|---|
| 定时器到期 vs `cancel(task)` | 谁先到 `wake`/`fail_wait` 谁赢 | 定时器赢：任务恢复，但 `rethrow_wait_error()` 仍抛取消异常（`cancel_requested` 粘性）；取消赢：定时器条目惰性无害 |
| `notify_all()` vs `cancel(task)` 同一等待者 | 决定谁先进 CAS | 事件侧的等待槽在下次扫描时因 `is_active_wait()` 为假被跳过 |
| 发送者交值 vs `channel.close()` | 决定谁先进槽 | close 赢：发送者以 `ChannelClosedError` 失败并**保留其值** |
| `close()` 排空接收者 vs 接收者被取消 | 谁先进槽 | 已取消的接收者被跳过，缓冲值留给下一个接收者 |
| 两次 `notify_one()` vs 单个自动复位信号 | 第一次消费挂起信号，第二次记为新的挂起信号 | `signaled_` 对自动复位是**单标志**，绝不是计数器 |
| 将取消任务的下一 await 点 vs 已完成的操作 | **检查点先抛**：`rethrow_wait_error()` 先查 `wait_error`，再查取消标志，**然后**才返回值 | 值就是不会被交付 |
| 任务内调用 `cancel_all()` | 调用者**也被取消**（转 `Cancelling`） | `tasks_cancelled` 把调用者计入 —— 它是关机原语，不是"取消别人" |

---

## 四、线程契约

**恰好一个线程**执行协程、做状态迁移、销毁帧：调用 `run()` 的那个线程（"循环线程"）。
库里其它一切假设这一点 —— 这正是无锁代号协议成立的前提。

**只有 4 个入口跨线程安全**，且全部靠"给循环线程**排队**"实现，自己什么都不碰：

| 入口 | 机制 |
|---|---|
| `post(fn)` | 互斥量下追加到外部队列，notify CV |
| `request_stop()` | 置原子标志，notify CV |
| `cancel(id)` | 把 `cancel_impl(id)` 追加到外部队列，notify CV |
| `TimerHandle::cancel()` | 在 `TimerControl` 上置原子标志，notify CV |

其它都**不安全、也不需要**安全。外部线程取消一个 park 的任务，只用 `cancel()` 即可。

---

## 五、不变量 ↔ 落点对照

| # | 不变量 | 由什么保证 |
|---|---|---|
| I1 | 就绪队列里一个 id 至多一次 | `wake`/`fail_wait` 只从等待态入队；`begin_wait` + 代号检查让第二次入队不可能 |
| I2 | 出等待态需 id 与代号同时匹配 | `wake()` / `fail_wait()` / `is_active_wait()` |
| I3 | 帧只在「终态 + 无消费者需要 + 不在任何队列」时销毁 | `reclaim_pending()` 在回收时**重查**状态与 `awaiter_refs`，必要时经 `reclaim_when_unref` 延后 |
| I4 | 每个帧恰好销毁一次 | `TaskRecord::alive` 在 `handle.destroy()` **之前**清；析构器只碰活记录 |
| I5 | 终态无出边 | `finish_task()` / `final_suspend()` 是终态唯一写入者；`is_terminal()` 守卫每个写入路径 |
| I6 | 已取消的任务不被 resume 两次 | 与 I2 同一套代号协议 |
| I7 | 运行时内无忙等 | 唯一的阻塞调用是 `wait_for_work()` 里的条件变量 `wait_until` |

---

## 六、可参照的压力规模（单线程 / Release 实测量级）

用于判断"我的实现慢不慢"，不是性能目标：

| 场景 | 规模 | 耗时 |
|---|---|---|
| 超短生命周期任务 | 10 万 | ~98 ms |
| 定时唤醒 | 2 万 | ~63 ms |
| 同时取消 | 1 万 | ~117 ms |
| 事件等待者统一唤醒 | 1 万 | ~17 ms |
| 消息经 4×4 通道 | 5 万 | ~37 ms |
| 单消费者严格保序 | 5 万 | ~44 ms |
| await 链深度 | 2000 | ~3 ms |
| 定时器 创建/取消/触发 | 2 万 / 1 万 / 1 万 | ~35 ms |

> 注意量级本身就说明问题：如果"1 万个定时唤醒"要几秒，先怀疑是不是**每轮重建容器/重复扫描**
> 而不是常数因子差。

---

## 七、文档化契约的写法（可复用）

把这类语义写进注释/README 时，用**"触发 → 结果"的判据式表述**，不要写故事：

- ✅ "一次性回调定时器维持循环存活；周期性定时器不维持 —— 必须显式停掉，否则 `run()` 不返回。"
- ❌ "我们上次发现 demo 不退出，调了半天。"

把每条不变量写成可读语句（而非代码片段），并注明**它在哪一行被保证**——这样评审时能靠阅读
验证，而不是靠跑出来。
