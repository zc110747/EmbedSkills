---
name: deterministic-clock-testing
description: 把时间抽象成可注入TimerLike+FakeTimer,让依赖延迟/节流/超时/重试的代码可确定性测试(无真实sleep)。含最小接口、FakeTimer四要点、四类断言。触发:定时器测试、节流测试、flaky测试、假时钟、确定性测试。
agent_created: true
---
# 确定性时钟测试 · 可注入 TimerLike + FakeTimer

## 何时用

被测代码里有"时间维度"时：

- 延迟生效（传输延迟、防抖、退避重试）
- 节流 / 去抖 / 采样周期
- 连续过程收敛（仿真、动画、渐进逼近）
- 超时判定
- "停下来之后要停止空转"

这些代码若用真实 `setTimeout` / `setInterval` 测试，只有两种结局：**慢**（真等），
或**flaky**（CI 负载一高就挂）。而且"延迟未到时不产生输出"这类断言根本无法可靠验证。

## 一、最小接口面

只抽被测代码真正用到的能力，不要做通用调度器：

```ts
export interface TimerLike {
  now(): number;
  setInterval(fn: () => void, ms: number): number;
  clearInterval(handle: number): void;
  setTimeout(fn: () => void, ms: number): number;
  clearTimeout(handle: number): void;
}

export const realTimer: TimerLike = {
  now: () => Date.now(),
  setInterval: (fn, ms) => setInterval(fn, ms) as unknown as number,
  clearInterval: (h) => clearInterval(h),
  setTimeout: (fn, ms) => setTimeout(fn, ms) as unknown as number,
  clearTimeout: (h) => clearTimeout(h),
};
```

被测类构造时 `timer = options.timer ?? realTimer`，生产零改动，测试注入即可。

**关键**：`now()` 必须是**单调**的，且与定时器共用同一时间轴 ——
否则"经过 14ms 时定时器还没触发"这类断言不成立。

## 二、FakeTimer 的四个实现要点

```ts
export class FakeTimer implements TimerLike {
  private t = 0;
  private seq = 0;
  private readonly jobs = new Map<number, { at: number; fn: () => void; interval: number | null }>();

  now() { return this.t; }

  setInterval(fn: () => void, ms: number) {
    const id = (this.seq += 1);
    this.jobs.set(id, { at: this.t + Math.max(0, ms), fn, interval: Math.max(1, ms) });
    return id;
  }
  clearInterval(handle: number) { this.jobs.delete(handle); }

  setTimeout(fn: () => void, ms: number) {
    const id = (this.seq += 1);
    this.jobs.set(id, { at: this.t + Math.max(0, ms), fn, interval: null });
    return id;
  }
  clearTimeout(handle: number) { this.jobs.delete(handle); }

  advance(ms: number) {
    const end = this.t + ms;
    for (;;) {
      let nextId = -1;
      let nextAt = Number.POSITIVE_INFINITY;
      for (const [id, job] of this.jobs) {
        if (job.at > end) continue;
        if (job.at < nextAt || (job.at === nextAt && id < nextId)) { nextAt = job.at; nextId = id; }
      }
      if (nextId < 0) break;
      const job = this.jobs.get(nextId);
      if (!job) break;
      this.t = job.at;                      // ② 先推进时间到到期时刻
      if (job.interval === null) this.jobs.delete(nextId);
      else job.at = this.t + job.interval;  // ③ interval 重排（在调用 fn 之前）
      job.fn();                             // ④ 回调里可能 clear 掉自己
    }
    this.t = end;                           // ⑤ 收尾归位
  }

  pending() { return this.jobs.size; }
}
```

四个要点，每个都有实际踩坑：

1. **按到期顺序执行，同刻按注册顺序**（`id` 递增，天然稳定排序）。
   不排序的话，多个定时器交叉时会得到与真实运行不同的顺序。
2. **回调执行前就把 `this.t` 推到 `job.at`** —— 回调里读 `now()` 必须看到"此刻"，而不是 `advance` 开始时的时刻。
   否则依赖 `now()` 计算耗时的逻辑（如节流的 `lastSendAt`）会算错。
3. **interval 的 `at` 在调用 `fn` 之前重排**。若放在 `fn` 之后，回调里 `clearInterval` 自己会失效（已被重排）。
4. **回调里可能 clear 自己** —— 这是"收敛后停止空转"的常态，所以循环每次都要重新取 `jobs.get()`，
   不能在循环外缓存 job 引用。

`advance` 结束后把 `t` 设回 `end`：确保"推进 14ms"精确等于 `now() === 14`，
而不是停在最后一个到期任务的时间点。

## 三、四种典型断言

```ts
// ① 延迟前零输出
timer.advance(14);
expect(states).toHaveLength(0);
timer.advance(1);
expect(states.length).toBeGreaterThan(0);

// ② 每 tick 恰好步长（不越界）
timer.advance(15);                       // 送达瞬间走一步
expect(actual).toBeCloseTo(home + 4.8, 9);
timer.advance(20);                       // 之后每 20ms 一步
expect(actual).toBeCloseTo(home + 9.6, 9);

// ③ 收敛后不空转 —— 最硬的一条，能抓住"忘了 clearInterval"的 bug
timer.advance(2000);
expect(timer.pending()).toBe(0);

// ④ 节流：实际次数远小于调用次数
expect(sent).toBeGreaterThan(10);
expect(sent).toBeLessThan(80);           // 400 次命令变化，约 1600ms / 33ms ≈ 49
```

③ 值得单独强调：多数"定时器泄漏"在功能测试里完全看不出来（结果是对的，只是永远在跑）。
`pending() === 0` 是唯一能自动抓住它的断言。

## 四、与节流组合时的两个坑

- **尾沿（trailing edge）节流必须有"最后一帧补发"**。只做丢弃不补发，拖动结束时会停在半路。
  测试要覆盖：停止调用后 `advance` 一个节流周期，最后那帧必须发出去。
- **节流的 `lastSendAt` 初值用 `Number.NEGATIVE_INFINITY`**，而不是 `0`。
  用 0 时若窗口起点也是 0，第一次调用会被误判为"在窗口内"而延迟，产生 33ms 的假延迟。

## 五、经典误用：用观测日志做瞬时断言

"日志里出现 X"这类观测手段往往**带合并/节流**（如 500ms 合并写一条、200ms 轮询刷新）。
它们的出现时刻**远晚于**真正的状态变化，因此：

- ✅ 只能用于**稳态**断言（"链路通了"）
- ❌ 不能用于**瞬时**断言（"此刻还没跟上"）

瞬时断言必须在触发动作后**立刻**读状态，而不是等某个观测信号。
（Web 端的具体表现与修法见 skill `web-headless-verification` 硬坑 5。）

## 六、一句话流程

1. 被测代码里所有 `Date.now()` / `setTimeout` / `setInterval` → 换成注入的 `timer`。
2. 测试里注入 `FakeTimer`，用 `advance(ms)` 替代 `await sleep(ms)`。
3. 断言优先写"边界时刻"：**差 1ms 不生效 / 到点生效**。
4. 连续过程类代码，务必断言 `pending() === 0`。
5. 生产代码零改动（默认参数 `realTimer`），测试与生产走同一套逻辑。

> 同样模式可直接移植到 Python（`time.monotonic` / `threading.Timer` 的薄封装 + 手写假时钟），
> 思路一致：**把时间变成依赖注入的接口，而不是调用全局函数**。
