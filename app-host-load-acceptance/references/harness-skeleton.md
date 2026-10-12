# 通用 harness 骨架：设计说明与演进顺序

配套 `app-host-load-acceptance/SKILL.md` §4。代码见 [`../scripts/net_load_harness.py`](../scripts/net_load_harness.py)
（stdlib-only，可直接嵌入你的 `verify_*.py`）。

---

## 一、六个组成部分与各自存在的理由

| 组件 | 职责 | 为什么必须有 |
|---|---|---|
| `Checks` | 记录 PASS/FAIL、不早退、末尾汇总 + 退出码 | 一次运行给出**全貌**；失败信息不被第一个异常截断 |
| `wait_until` | 轮询谓词直到成立或超时 | 所有"等前置条件"的唯一实现，避免散落的 `sleep` |
| `ServerProcess` | 启进程 + 独立线程收 stdout + 快照 + 控制台命令 + 带超时的退出 | 见下面四条 |
| `Client` | 一个真 TCP 连接，**记录包边界** | "包"与"字节"必须分开（纪律 C） |
| `connect_many` | 同时并发的批量连接 | 串行连接会排空内核队列，掩盖 backlog 问题 |
| `first_difference` | 差异定位（偏移 + 字节） | 失败信息必须精简，别打 32 KB 原文 |

---

## 二、`ServerProcess` 的四条硬要求

### 1. 独立读取线程 + 快照

```python
self._reader = threading.Thread(target=self._pump, daemon=True)
...
def snapshot(self) -> list[str]:        # 断言侧只读快照
```

**不要**让断言代码 `readline()` 等某一行 —— 那会把"读日志"和"断言什么"耦合在一起，
一旦某条日志没出现，测试就**卡死**而不是**失败**。

### 2. `errors="replace"`

```python
text=True, errors=self.decode_errors, bufsize=1
```

被测服务的错误路径上只要有一个非 UTF-8 字节，严格解码就会让**读取线程静默死掉**：
表现为"日志停在 N 行 + 退出码永远读不到"。这个现象**极具误导性**，会让人去查服务是不是挂了。

### 3. 计数从**新**行读（基线式）

```python
def stats(self, cmd="stats", prefix="[stats]", timeout=15.0) -> dict:
    baseline = len(self.snapshot())     # ← 先记基线
    self.console(cmd)
    line = self.wait_new_line(baseline, lambda l: l.startswith(prefix), timeout)
    ...
```

这是 §1 纪律 B 的实现。少了 `baseline`，你会读到**上一轮**的行，
`packets_out` 读成 0，看起来像"服务根本没转发"。

### 4. 退出**带超时**

```python
def stop(self, quit_cmd="quit", timeout=20.0) -> int | None:
    try: self.console(quit_cmd)
    except Exception: pass
    try:    return self.proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        self.proc.kill(); self.proc.wait(timeout=5); return None
```

`return None` 表示"超时未退出" —— 让调用方**显式断言** `exit_code == 0`。
**不要**在 harness 里吞掉超时。

---

## 三、`Client`：把"包"和"字节"分开

```python
def packets(self) -> list[bytes]:   # 每次 recv() 的原始返回，边界保留
def received(self) -> bytes:        # 拼接后的字节流
def hit_once(self, tag) -> int:     # tag 作为【独立包】出现的次数
def was_split(self, tag) -> bool:   # tag 出现了，但从未作为独立包出现
```

三者对应三种强度不同的断言。**只提供 `received()` 的 harness 会诱使你写出错误的断言**
（`tag in received()` 在 TCP 合并后恒真）。

### 自检就是最好的说明

本骨架的 `__main__` 自检会在本机真实建一对 loopback socket，服务端连发两个 `sendall`：

```
两次 sendall 在本机常常被合并成一个 recv()。
自检因此断言两条【皆可】的事实：
  - 要么收到两个独立包（hit_once("one") == 1）
  - 要么收到一个合并包（packets == [b"onetwo"]），此时 was_split("one") 必须为 True
```

实测 5 次里 4 次是**合并**、1 次是分开 —— 一个自带演示的 harness。
运行：`python net_load_harness.py`。

---

## 四、演进顺序（怎么从零长出来）

不要一次写完 800 行。按这个顺序长，每一步都可运行：

1. **`Checks` + `wait_until`** —— 先把"怎么算一次 PASS"定下来。
2. **`Client`** —— 能连、能发、能收、能拿到 `packets()`。
3. **一个极小的场景** —— 两个客户端，A 发 B 收。此时脚本已经**能失败**（不是恒绿）。
4. **`ServerProcess`** —— 加进程管理（启动 + 等端点 + 收日志快照 + 优雅退出）。
5. **`connect_many`** —— 加并发连接。
6. **计数读取（基线式）** —— 加 `stats()` + `wait_for_counter()`。
7. **场景逐个加** —— 规模扇出 → 突发 → 背压 → 抖动 → 关闭（见 `load-scenarios.md`）。
8. **跑负向对照** —— 用坏二进制确认有牙齿（见 `negative-control.md`）。
9. **接进 CTest 的快速子集** —— 挑一个**确实越过了已知边界**的规模（本项目选 100，
   因为 `FD_SETSIZE` 是 64），而不是随便挑一个小数字。

---

## 五、常见自伤（都在本项目真实发生过）

| 自伤 | 症状 | 修法 |
|---|---|---|
| 用"存在某行"当等待条件 | 读到上一轮的旧行，计数为 0 | `stats()` 里的基线式等待 |
| 等待条件不基于基线 | 前置的 2 个到达让 `wait_arrivals(2)` 立刻成立，探测包被转发给空集合 | 等待 `before + 1` |
| 用 `tag in received()` 判整包 | 合并后恒真 | `hit_once(tag) == 1` |
| 失败信息打印完整 payload | 32 KB 刷屏，真失败被埋 | `first_difference()` |
| 读子进程 stdout 没写 `errors=` | 读取线程静默死掉，"日志停在 N 行" | `errors="replace"` |
| 断言前不等成员数到位 | `online=973/1000` 的假失败 | `wait_for_counter()` |
| 临时构建目录名没被 `.gitignore` 覆盖 | 仓库根冒出 `build-verify-*.log` | 用 `<ignore 匹配的模式>`；`git check-ignore -v` 复核 |
| 忘了 `__pycache__/` | `app/tools/__pycache__/` 混进待提交列表 | `.gitignore` 加 `__pycache__/`、`*.pyc` |

> 注意上表里**只有前两行是"逻辑错误"**，其余全是"度量本身有 bug"。
> 这也是本仓反复出现的教训：**当结论看起来是"被测对象有 bug"时，先把度量本身证伪。**
