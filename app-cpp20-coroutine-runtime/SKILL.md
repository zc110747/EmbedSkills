---
name: app-cpp20-coroutine-runtime
description: 自建/使用 C++20 协程运行时的判据与静默失败：header-only 的 inline/ODR 漏网、generation 计数替代锁、帧归属与泄漏断言、定时器堆惰性删除、通道背压。触发：C++20 协程、co_await 卡住、双重 resume、协程帧泄漏、重复符号。
agent_created: true
---

# C++20 协程运行时：设计判据与静默失败

自建或深度使用**单线程协作式**协程运行时（调度器 + `Task<T>` + 定时器 + 事件 + 通道 + 取消）
时，故障几乎都是**静默的**：双重 resume、帧泄漏、回调定时器整批不触发、`co_await` 再也不醒——
都不报错、不一定崩溃，测试还可能全绿。本文只写「反直觉、且换项目仍成立」的部分。

> 前缀 `app-` = **上位机 / 服务端应用层**（非固件）。固件侧 C++ 见 `mcu-cpp-development`。

## 何时用
- 实现或修改协程调度器 / `Task<T>` / awaiter；现象是 `co_await` 卡住或恢复两次。
- 把带 `.cpp` 的协程库改成 header-only；或在链接期看到 `multiple definition`。
- 用挂钟时间断言定时行为，结果偶发失败（flaky）。
- 需要**证明**「没有协程帧泄漏」。

---

## 1 · 五条不变量（先记这五条，其余都是推论）

| # | 不变量 | 违反后的症状 |
|---|---|---|
| I1 | 一个 task id 在就绪队列里**至多出现一次** | 同一帧被 resume 两次 → 未定义行为 |
| I2 | 出等待态必须 **(id, generation) 同时匹配** | 陈旧定时器 / 陈旧通道槽把任务再唤醒一次 |
| I3 | 帧只在「终态 + 无消费者还需要结果 + id 不在任何队列」时销毁 | 读到已销毁帧里的结果 |
| I4 | 每个帧**恰好销毁一次** | 泄漏，或 double-free |
| I5 | 终态是**吸收态**，无出边 | 已取消/已结束的任务又被 resume |
| （I6） | 运行时里**没有一处忙等** | CPU 空转 / 循环不响应外部事件 |

验证手段只有两个可信：**进程级帧计数平衡**（§3）与**多 TU 链接测试**（§5）。
"看代码觉得对"不算证据。

## 2 · 唤醒协议：用 generation 计数，不要用锁

单个协作式线程上，一个挂起的任务可能**在同一轮**被四方同时唤醒：定时器到期、事件
`notify`、`channel.close()`、`scheduler.cancel(id)`。没有保护就会有两个调用各自 `wake()`
同一个任务 → 双重 resume。

正解不是加锁（全程单线程，锁只会掩盖问题），而是**注册即带唯一代号**：

```
begin_wait(t, s) -> gen   // 自增 wait_gen、记下状态、返回新代号
abort_wait(t, gen)        // 决定「不挂起」时把状态还原（同步完成路径）
wake(t, gen) -> bool      // 状态仍是等待态 且 gen 仍匹配：第一个调用者赢，其余 false
fail_wait(t, gen, err)    // 同 wake，但附一个在 await 点抛出的错误
```

- `wake` 本质是对 `(task, generation)` 的 **compare-and-swap**：第一个成功者把状态翻出等待态，
  后来者一律 `false`。
- 代号过期的注册**天然惰性**：陈旧定时器条目、陈旧通道槽永远匹配不上，因此无害。
  好处是「陈旧处理被局部化到唤醒方」，不需要任何一方去扫描堆/链表"反注册"，也就不会有
  双份记账漂移。
- **`abort_wait` 不能省**：awaiter 在 `await_suspend` 里发现能同步完成（通道有空间、事件已置位、
  截止时间已过）时，`begin_wait` 已经改过状态了；必须还原，否则任务永远"在等待"却没人会唤醒它。
  它对代号失配必须是 no-op——期间可能真的来了一个取消，把它移出了等待。
- 代价：陈旧条目要**惰性删除 + 周期性压实**（§6），否则堆/链表无界增长。

## 3 · 帧所有权与「无泄漏」的判据

- 让**控制块（TCB）成为 promise 的成员**，而不是单独分配的对象。收益两条：
  ① TCB 生命周期 ≡ 帧生命周期，没有第二个对象可泄漏或双重释放；
  ② 调度器只持有**非拥有**记录 `{TCB*, handle, alive, last_state}`。
- `alive == false` 意味着 TCB 指针已悬垂 → 所有查询统一走 `control_of(id)`（死记录返回
  `nullptr`），于是**陈旧 id 是良性 no-op 而不是 use-after-free**。
  腾出 `alive` **之前**先把 `last_state` 写进记录，这样"任务早已结束"仍可查终态。
- **`co_await child` 的悬空窗口**：父要在子**结束之后**读子的结果，所以子进入终态时不能立即销毁帧。
  做法：`await_suspend` 给子 `awaiter_refs++` 并记下 `continuation=parent`；子进入终态时置
  `reclaim_when_unref`，**只有** `awaiter_refs==0` 才入回收队列；父在 `await_resume`
  **读值之前** release。再配一条兜底：回收一个仍设着 `awaiting_child` 的 TCB 时，代它释放那次引用
  → 引用计数永不被搁浅。
- **`frames_created == frames_destroyed` 才是有效的泄漏断言**，且计数器必须是**进程级**
  （函数局部 `static`，靠 `inline` 保证全程序一份）。单实例计数抓不到「帧活得比调度器久」。
  测试里用**增量**，不要用绝对值。

## 4 · 取消是状态，不是信号

- `cancel_requested` **粘性且幂等**。`cancel()` 从不销毁挂起的帧、从不从协程内部把它掀翻：
  - **等待中**的任务 → 置 `wait_cancelled` 后唤醒，await 点抛取消异常，帧**正常展开**；
  - **运行中**的任务 → 转 `Cancelling`，在**下一个 await 点**（显式取消检查点也算）才生效；
  - **就绪未启动**的任务 → 在函数体跑之前直接结束。
- 帧永远正常展开 ⇒ 协程体内**每个析构函数都会跑**。这就是取消的 RAII 全部故事，也是
  「协程被取消就丢资源」这类担心的解药。
- 注意**不对称**：任务即便 **catch 住**取消异常后正常返回，终态**仍是 `Cancelled`** ——
  请求已被受理，调用方不能把它误当成功。
- `cancel_all()` 会取消**调用者自己**（它是关机原语，不是"取消别人"）；计数里含调用者。
- 取消不能回收帧：回收只看「终态 + 无引用」，与取消是两条正交路径。

## 5 · header-only 四条硬约束

| 约束 | 违反后的症状（**都不在编译期**） |
|---|---|
| 每个非模板定义 `inline` | 链接期 `multiple definition of ...`；单 TU 测试**永远测不到** |
| 线程局部量用 `inline thread_local` 且放**命名空间**内 | 匿名 namespace 在头里 = **每个 TU 各一份** → `current()` 在别的 TU 读到 `nullptr` |
| 进程级计数器用 `inline` 函数局部 `static` | 每 TU 一份 → 泄漏断言恒成立或恒不成立 |
| **必须有一个多 TU 可执行文件**做红测 | 否则漏 `inline` 要等消费者来踩 |

- **负向对照（证明测试有牙齿）**：临时去掉某函数（如 `Scheduler::run()`）的 `inline`，应看到
  `multiple definition of '<ns>::Scheduler::run()'` + `first defined here`。修完必须把 `inline` 加回去，
  别把实验状态提交进去。
- 头里调函数局部 `static`（单例 / 全局计数器）是唯一能在 header-only 下保有"全程序一份"的写法。
- CMake 用 **INTERFACE 库**（不编译、不产出 `.a`/`.lib`）。给 INTERFACE 库设编译选项必须用
  `INTERFACE` 作用域 —— `PRIVATE` 用在 INTERFACE 库上会直接报错。
- GCC 15 起 `-Wmissing-declarations` 对 C++ 生效：**跨 TU 共享的非 `inline` 函数必须先有声明**。
  库侧全 `inline` 恰好免疫，但测试夹具会被咬（补一个 `*_api.hpp` 声明头即可）。
- 头里的 `main()` **不能加 `inline`**（标准禁止）；只在单 TU 可执行文件里定义，用
  `NO_MAIN` 宏给需要自带 `main()` 的用例退让。
- 代价是编译时间：大 TU 里包含**窄头**（`scheduler.hpp`）而不是伞头（`coroutine.hpp`）。

## 6 · 定时器堆：惰性删除 + **原地** compact

- 二叉最小堆按 `(deadline, sequence)` 排序。**`sequence` 兜底不可省**：Windows 的
  `steady_clock` 被系统定时粒度量化（≈15.6 ms），同批定时器大量共享 deadline，
  没有 tie-break 就没有确定顺序。
- 取消是 O(1)：`cancel()` 只置原子标志 + 唤醒循环；堆条目**惰性**清（`expire` 时跳过，
  `prune` 时批量压）。
- **`compact()` 必须原地写游标**（`remove_if` 式）。真实事故：早期版本把存活条目 `std::move`
  进临时 vector，然后在「没有死条目」时提前 return —— 堆里留下一批 **moved-from** 条目。
  条目里的 `shared_ptr<TimerControl>` moved-from 即 `null`，于是 `expire` 把**每个存活的回调
  定时器**都误判成"陈旧 task 条目"丢弃：**并发定时器 ≥128 个时，所有回调定时器集体不触发**
  （阈值来自 `prune` 的 `size() < 128` 早退——那是 `compact` 唯一可达的路径）。
  原地压实让"无死条目"路径成为严格 no-op。
- 教训：**回调型定时器的断言用 `fire_count()`，不要用挂钟时间。**

## 7 · 通道：三条投递路径与背压的观测量

投递优先级（固定，不可打乱）：**① 直接交接**（有挂起的接收者在等 → 直接 move 进它的槽，
不缓冲）→ **② 缓冲**（`size() < capacity`，若有字节预算函数则还要 `used + cost <= budget`）
→ **③ 挂起**（发送者 park，值仍归**发送者帧**所有，直到通道收下）。

- 接收侧顺序：先缓冲，再挂起的发送者，最后才是 `Closed`。
- **公平 + 内存有界的机制**：一次接收腾出槽后，`refill_from_buffer` **至多**把一个挂起的发送者
  拉进缓冲并唤醒它（不是一次全拉）。于是**背压的表现就是"挂起的发送者"**——可直接观测
  （`sender_count()`），不用去猜。
- `close()` 是**非对称**的：所有挂起的**发送者**以 `ChannelClosedError` 失败（它们的值从未被
  收下，仍归自己）；挂起的**接收者**则继续被缓冲喂饱，缓冲排空后才失败。
  「关通道 → 继续排空」正是流水线的正确收尾写法。
- 想在容量之外再加一个**字节维度**的背压，就在其上叠字节记账 + 通道级 `next_sequence()`
  （防生产者自造冲突 id）+ 序号连续性检查（丢包/乱序立刻可见）。

## 8 · 测试纪律：不要赌挂钟

- Windows 定时粒度 ≈15.6 ms ⇒ 短定时器同批触发。断言只用：`fire_count()`（回调触发次数）、
  就绪队列顺序、发送路径内采样、`sender_count()`。
- **协作式调度的确定性触发器**：想断言"此刻恰好 N 个任务在等待"，不要用短 sleep 当探针
  （Debug 下 1 ms 内跑不完，探针会提前读到中间值 → 约 1/18 概率 flaky）。改成**两阶段**：
  阶段 1 用 `run()` 让前置任务确定性收官；阶段 2 先 spawn N 个长时间挂起者，**最后**再 spawn
  一个"触发器"任务 —— 靠就绪队列 FIFO 保证它在 N 个都 park 之后才被调度。
- 终止条件要显式：`run()` 在「无非终态任务」**且**「无尚可触发的一次性回调定时器」时返回；
  **周期性定时器刻意不维持循环存活**（否则 demo 永不退出），必须靠丢弃/取消句柄或 `request_stop()`。
  退出前跑一次全量 `prune`，让 `pending_timer_count()` 这类事后诊断精确，而不是"每个取消的
  定时器留一条垃圾"。
- 循环里**只有一个阻塞调用**（条件变量 `wait_until(最近 deadline)`）：`post()`、`cancel()`、
  `request_stop()`、`TimerHandle::cancel()` 都要 notify，否则停机会等满一个 deadline。

## 9 · 反模式速查

| 反模式 | 后果 |
|---|---|
| 把**临时 lambda** 当协程函数体 | 闭包不复制进帧，帧持悬垂引用 → 全部改命名空间级自由协程函数 |
| 假设异常在子任务被吞掉 | 异常**穿透每一层 awaiting 帧**：子抛且父未 catch，父子都记 Failed（计数 +2） |
| 用 `clear_finished()` 后又查老 id | 老 id 与"从未存在"都读回 `Created`，不可区分 |
| 在 `run()` 返回后读 `stop_requested()` | `run()` 退出时会清它（这是调度器可复用的原因）；要在回调**内部**断言 |
| `Result<T>` 当全局错误模型 | 它只是"不抛异常的 try_send/try_receive"的载体；失败子任务一定从 `co_await` 抛回来 |
| 跨调度器 `co_await` | 两个循环不可能在同一线程交错 —— 应在 `await_suspend` 直接抛逻辑错误 |
| 指望有抢占 | 没有。协程不 await 就永久霸占循环；解法是在循环里放取消检查点/`sleep_for` |
| 单线程却到处加互斥量 | 掩盖双重 resume 等真问题；正确做法是 generation 协议 + 明确的线程契约 |
| 销毁带挂起等待者的对象（事件/通道）时直接释放 | 必须在析构里**同步**给每个等待者置错误并移入就绪（`ObjectDestroyedError`），否则等待者永不醒 |

## 参考
- [`references/runtime-design.md`](references/runtime-design.md) — 事件循环**顺序**表与每一步的理由、
  空闲/终止语义、线程契约（哪几个入口线程安全）、不变量与代码位置对照、压力规模参考数字
- [`references/state-machine.md`](references/state-machine.md) — 状态集合、完整转移表、归属表、
  竞态裁决表、"赢家/输家看到什么"
- [`references/header-only-odr.md`](references/header-only-odr.md) — 四条约束的完整落地、CMake INTERFACE
  写法、负向对照命令与期望报错、`-Wmissing-declarations` 细节
- [`references/test-discipline.md`](references/test-discipline.md) — 确定性测试四要点、flaky 案例与修法、
  可参照的压力规模数字
