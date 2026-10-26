---
name: app-host-load-acceptance
description: 上位机网络服务的多客户端规模压测与验收方法：参数化 N 客户端 harness、pass/fail 计数、断言前先等前置条件、stats 基线防读旧行、包边界与字节相等分层断言、负向对照证明测试有牙齿。触发：压测脚本、1000 客户端、负载验收、测试恒绿或 flaky。
agent_created: true
---

# 上位机网络服务的规模压测与验收（完整判据原文 · 由 app-host-load-acceptance 并入）

"5 个客户端全绿"**不能**推任何关于 1000 个客户端的结论。规模压测要回答的是另外几个问题：
**无损吗？有背压吗？有泄漏吗？退出干净吗？以及 —— 这个脚本会不会恒绿？**

> 前缀 `app-` = **上位机 / 服务端应用层**（非固件）。固件侧验收见 `embedded-verification-acceptance`；
> 被测服务本身的规模上限见 `app-select-relay-server`。

## 何时用
- 要给一个 TCP 服务（中继 / 网关 / 长连接）做**多客户端规模**验收。
- 已有的测试"总是通过"，需要判断它是**真的对**还是**恒绿**。
- 压测断言偶发失败（flaky），或读到的计数看起来像"服务什么都没干"。

---

## 1 · 三条纪律（先立规矩，再写场景）

### 纪律 A：**断言之前，先等前置条件**

最经典的假失败：1000 个客户端**同时在冲连接**，内核握手全部完成 ≠ 服务已经 `accept()` 完它们。
此刻去读 `stats`，`online` 可能是 **973/1000** —— 看起来像"服务器丢了连接"，其实只是采样太早。

```
burst_connect(N)                    # 0.2 s 内全部返回
stats  -> online=973                # ✗ 假失败
```

**正解**：断言前先等"房间成员数到位"。

```
burst_connect(N)
wait_members(server, N, timeout=20) # 读 accepted/online，等它稳定到 N
assert online == N                  # ✓
```

> 这是本仓反复出现的**同一条纪律**：任何"断言某状态"的地方，前一行都必须是"等它该成立"。
> 也是唯一能同时消除"假失败"和"掩盖真失败"的做法 —— 超时了就如实报失败，而不是放宽断言。

### 纪律 B：**读计数之前，先记基线**

用"存在某行"当等待条件，会**立刻**满足于**上一轮**的旧行：

```python
# ✗ 错：缓冲里早就有 [stats] 行，条件立刻成立 -> 读到上一轮的 0
console("stats"); wait_until(lambda: any(l.startswith("[stats]") for l in snapshot()))
```

于是 `packets_out` 读成 0，看起来像"服务器根本没转发"。
**正解：记下基线行数，等"新增"的那一行**（`wait_for_new_line(baseline, ...)`）。

同样的形态也出现在"等 N 个客户端到达"上：如果**之前**已经有 2 个到达过，
`wait_arrivals(server, 2)` 会立刻成立，于是探测字节在目标成为成员**之前**就被转发掉
（转发给了空集合 = 丢包）。⇒ 等待条件必须是**基于基线的**（`before + 1`）。

### 纪律 C：**断言分层 —— 包边界 ≠ 字节相等**

TCP 是流。服务"一包一次 `send()`"并不保证对端"一包一次 `recv()`"：

| 断言类型 | 能无条件断言吗 | 做法 |
|---|---|---|
| **字节内容与顺序** | ✅ 可以 | 直接比对收到的字节 |
| **包边界**（两个包不被合并） | ❌ 不行 | **给发送方加节奏**：发一个 → 等对端收到 → 再发下一个 |
| **不被拆包** | ✅ 可以 | 判据是"恰好命中某个包一次"，**不是** `tag in stream` |

- 判"整包到达"**不能用子串匹配**：TCP 允许把两个 `send()` 合并成一个 `recv()`，
  合并后 tag 依然完整，但它**不在任何独立包里**。正解是"tag 恰好命中某个包一次"
  （既没被拆、也没重复）。
- 把边界断言和字节断言混在一起写，会得到**"测出来的是内核行为、不是服务行为"**的假结论。

---

## 2 · 覆盖矩阵与"唯一的无损证明"

每个规模 N 上跑同一组场景：

| 场景 | 断言什么 | 为什么是它 |
|---|---|---|
| **规模连接 + 扇出** | `accepted/online/peak == N`、`rejected == 0`；**包括最后被 accept 的那个客户端**发一个包，N−1 个对端都收到 | 最后接入的那个正是历史上"隐身"的那个（见 `app-select-relay-server` §1） |
| **聚合恒等式** | `packets_out == 发送者数 × (N − 1)` **精确相等** | 唯一一个"整体无损"的证明；逐点断言给不出这个强度 |
| **突发连接** | 同时冲 N 个连接，`refused == 0` | 覆盖内核 backlog，而不是稳态 |
| **背压** | 一个停止读取的 peer 被丢弃 + 被计数 + **不影响其它 peer** | 背压必须是**按连接**的 |
| **连接抖动** | 4×200 轮连/断后 `online` 回到基线、`active_tasks` 回到基线 | 无泄漏（槽位 + 协程帧） |
| **优雅关闭** | 全部 N 个都被通知到、退出码 0、`frames_balanced == yes` | 满员时的收尾同样要能跑通 |

**实测参考**（Windows / MinGW-w64 / GCC 15.2 / Release / `poll_interval_ms: 5`，
16 个发送者、每 N 个客户端）：

```
    clients  connected  refused  connect s  fan-out s  packets_out
        100        100        0       0.05       0.10         1584   = 16×99
        300        300        0       0.07       0.10         4784   = 16×299
        500        500        0       0.10       0.21         7984   = 16×499
       1000       1000        0       0.22       0.21        15984   = 16×999
```

- `connect s` 是**同时**并发（每客户端一个线程）的墙钟；`fan-out s` 是从 16 个发送者
  第一个写出、到 N−1 个对端全部收到最后一个包的墙钟。
- 1000 客户端**空闲** CPU < 5%（单核）。

> 恒等式是这份测试的核心。**它一旦成立，就不需要"每个对端都逐条断言"** ——
> 后者在 N=1000 时是 O(N²) 的接收量，会让测试本身成为瓶颈，而且并不能给出更强的结论。

---

## 3 · 负向对照：证明**脚本**有牙齿

一个"永远 PASS"的脚本比没有脚本更危险。**唯一**的证伪方式：让它去测一个**已知坏的**二进制。

做法（复用被测服务的编译开关，不改生产代码）：

```bash
# 用同一份源码编一份"旧行为"的服务：把曾经的缺陷重新打开
g++ -std=c++20 -O2 -Iinclude -Iapp -DFD_SETSIZE=64 \
    app/chat_server.cpp app/net_socket.cpp app/yaml_config.cpp \
    -o /tmp/legacy/chat_server_legacy.exe -lws2_32 -static-libgcc -static-libstdc++ -static -pthread

python app/tools/verify_chat_load.py --server /tmp/legacy/chat_server_legacy.exe \
       --only-scale --clients 100 --senders 8
```

**期望结果：失败，且失败签名与最初的手工复现一致。**

实测：

```
FAIL  watch ceiling is 8191                  (got 63)
FAIL  every burst client is accepted         (refused 37)
FAIL  packets_out == senders*(clients-1)     (got 372, expected 792)
...                                          -> 11/18 FAIL
```

- 三个签名（`ceiling 63` / `refused 37` / `packets_out=372`）与"手工用真客户端复现"
  得到的是**同一组数字** ⇒ 脚本测的是**同一个缺陷**。
- 这种"用宏把旧缺陷重新打开"的做法很适合做对照，因为 `#ifndef` 保护让命令行 `-D`
  正好能复现旧行为（见 `app-select-relay-server` §1 的修法）。

> 负向对照要**跑一次并记下数字**，但**通常不进 CI**（它要求能编出一份坏二进制）。
> 作为"验收脚本交付时的自我证明"跑一次即可；也可以在脚本里留一个 `--legacy` 开关，
> 把编译命令固化下来，方便下次复核。

---

## 4 · harness 复用约定

多个验收脚本（端到端 / 启动器 / 规模）**必须共用一份**"什么是一个客户端"和"怎么计一次 PASS"。

```
verify_<service>_e2e.py      ─┐
verify_<service>_load.py      ├─  共用：ServerProcess / Client / check / check_eq / wait_until
verify_launcher.py            ─┘
```

**理由**：各写一份，就一定会出现"同一个行为，A 脚本算 PASS、B 脚本算 FAIL"——
之后没人再相信任何一个。

**硬性要求**：

- **stdlib only**（`socket` / `subprocess` / `threading` / `re`），不要引第三方 —— 验收脚本
  本身不能有依赖安装步骤。
- **真 socket 读字节**，不从日志反推行为。日志行只用于"**验证日志本身**"这类断言。
- 每个脚本末尾打印 `PASS (N checks)` 或列出所有 FAIL，退出码非 0 表示失败。
- 断言**不早退**：失败即记录并继续，让一次运行给出全貌。

现成骨架见 [`scripts/net_load_harness.py`](scripts/net_load_harness.py)（可直接嵌进脚本）。

---

## 5 · 子进程交互的四个坑

### 5.1 必须 `errors="replace"`

```python
subprocess.Popen(..., stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                 text=True, errors="replace", bufsize=1)     # ← errors 不能省
```

`text=True` 默认**严格解码**。被测服务在错误路径上吐出一个非 UTF-8 字节，
读取线程就会**静默死掉** —— 表现成"日志停在 N 行 + 退出码永远读不到"，
排查方向会被完全带偏。（见 `app-select-relay-server` 的 ASCII 契约。）

### 5.2 用**临时端口**而不是固定端口

服务要支持 `--port 0`（向 OS 要空闲端口），并**在启动横幅里打印真实端口**。
脚本用严格正则从横幅里解析（如 `...:(\d+)\s*$`）。

> 正则**故意写严**是有回报的：正是它抓到过"横幅把端口打成 `127.0.0.1:62031:62031`"的 bug
> （复用了返回 `ip:port` 的格式化函数）。

### 5.3 读取用**独立线程** + 可追加快照

不要 `readline()` 阻塞等某一行（顺序/时序耦合）。用一个后台线程持续 `readline` 追加进列表，
断言侧只做 `snapshot()` + `wait_until(pred, timeout)`。

### 5.4 退出是**有超时**的断言

优雅关闭要显式断言"进程在 X 秒内退出且退出码 0"。**不要**只 `terminate()` 收尾 ——
那会把"关机挂死"这个真实缺陷掩盖掉（真实案例：一个 detach 的控制台线程会让进程永不退出，
只有带超时的退出断言才抓得到）。

---

## 6 · 失败信息必须**精简**

`check_eq(actual, expected)` 直接打印两边原文时，一个 32 KB 的 payload 会让失败输出刷屏，
以至于**真正的那行 FAIL 被埋掉**。

改成**只打偏移与首个差异字节**：

```
FAIL  the 32 kB packet is byte-exact   (differ at offset 24576: 0x00 != 0xa5; 32768 bytes)
```

同理"采样"：N 大时不要对每个接收者都断言，**采样固定个数的接收者**并在断言文案里
注明 `(sampled 8 peers)` —— 让读者知道覆盖面，而不是误以为是全量。

---

## 7 · 落盘与清理边界

- 临时构建树（`build-verify/`、`build-verify-rel/`）用**带 `-` 前缀或后缀**的名字，
  确认被 `.gitignore` 的 `build-*/` 覆盖。
- ⚠️ **`build-*/` 只匹配目录**：落在仓库根的 `build-verify-cfg.log`、`build-verify-build.log`
  **不在忽略范围**，必须显式删除（否则会被 `git status` 抓出来）。
- 用 `git check-ignore -v <path>` 逐个确认，别靠"看起来像被忽略了"。
- 运行 Python 脚本会产生 `app/tools/__pycache__/` —— 记得 `__pycache__/` + `*.pyc` 进 `.gitignore`。

---

## 8 · 接进 CTest：**跑快速子集**

全量（100/300/500/1000）耗时太长，不适合每次构建都跑。做法：

- CTest 里注册**快速子集**（例如 `--clients 100,300`）；
- 关键判断：这个子集要**真的**能守住回归。本项目的子集是 `100,300`，而 100 **已经越过**
  `FD_SETSIZE=64` 那道墙 ⇒ 它就是一个**有效的**回归守卫，而不是"跑跑看"。
- 全量在交付/发布前手动跑一次，并**把数字记进 README**（时间、`packets_out` 恒等式）。
- 给 CTest 项设**足够的 TIMEOUT**（规模测试在慢机器上可能几十秒）。

```
ctest --test-dir build --output-on-failure
#   16/16 Test #16: app.chat_load ..................  Passed  12.52 sec
```

---

## 参考
- [`references/load-scenarios.md`](references/load-scenarios.md) — 每类场景的断言语义、构造方式与陷阱
- [`references/negative-control.md`](references/negative-control.md) — 负向对照的完整做法、期望失败签名、
  以及"脚本恒绿"的其它免疫手段
- [`references/harness-skeleton.md`](references/harness-skeleton.md) — 通用 harness 骨架说明与演进顺序
- [`scripts/net_load_harness.py`](scripts/net_load_harness.py) — stdlib-only 骨架：ServerProcess /
  Client / 计数器 / 基线式等待，可直接嵌入
