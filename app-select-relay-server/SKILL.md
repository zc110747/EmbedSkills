---
name: app-select-relay-server
description: 单线程 select() 网络服务的规模上限与可移植性：Windows FD_SETSIZE=64 令 FD_SET 静默截断、listen 必须非阻塞、backlog 要覆盖 accept 节奏、错误文本会本地化破 ASCII 契约。触发：客户端一多就丢数据、连接被拒、accept 挂死。
agent_created: true
---

# 单线程 `select()` 网络服务：规模上限、可移植性与运维契约

面向中继 / 网关 / 广播这类"**单线程 + `select()` 轮询 + 全量扇出**"的服务。
这类服务的规模故障有一个共同特征：**能连上、被计入在线数、然后数据被无声丢弃** ——
没有错误、没有日志、测试用少量客户端时全绿。

> 前缀 `app-` = **上位机 / 服务端应用层**（非固件）。压测与验收见 `app-host-load-acceptance`；
> 若事件循环是自研协程调度器，先读 `app-cpp20-coroutine-runtime`。

## 何时用
- 客户端数量一上去就丢数据 / 有客户端"发什么都收不到"，但连接是成功的。
- 出现 `WSAECONNREFUSED (10061)`、`ECONNREFUSED` 的**突发**失败。
- `accept()` 在运行一段时间后永久挂起，而 `select()` 一直报"有连接"。
- 服务日志里混进了乱码（非 UTF-8）字节，而契约声称输出是 ASCII。

---

## 1 · 致命一：`FD_SETSIZE` 在 Windows 是「静默截断」，不是上限

`FD_SET` **不返回错误**。满了就**不存**，调用方一无所知。

| 平台 | `FD_SETSIZE` | 越界行为 |
|---|---|---|
| Windows / MinGW-w64 | **64**（头文件默认值，可被宏改写） | **静默丢弃**：`fd_count` 停在 64，第 65 个起不存 |
| glibc / Linux | 1024（`__FD_SETSIZE`） | 越界**写栈**（未定义行为），内核不会看超过 1024 的位 |

实测（MinGW-w64）：`sizeof(fd_set) == 520`（64 × 8 字节句柄 + 8 字节计数）；
`FD_SET` 请求 100 个只存下 64 个。⇒ 一个"最多 64 个套接字"的服务：**63 个客户端 + 1 个监听**。

**症状的精确边界**：第 64 个及以后接入的客户端**能连上、被计入 `online`，但服务器从不 `recv()` 它们**
—— 它们发出去的一切被无声吞掉。边界值恰好是 `FD_SETSIZE`。

### ⚠️ 诊断陷阱：用 0 号客户端复现会得出**相反**的结论

扇出 / flush 通常遍历的是**客户端全表**，**不经过 `fd_set`**。所以高位客户端**收得到**广播，
只有**读**被挡住。若你让第 1 个连接的客户端发送，会看到"99/99 都收到了，一切正常"。

**正确复现方式**：让**高位**客户端（索引 ≥ 63）发送。

```
发送者 0 号  -> 99/99 收到        （假象：没问题）
发送者 62 号 -> 99/99 收到
发送者 63 号 -> 0/99 收到         ← 真实故障从这里开始
发送者 80 号 -> 0/99 收到
```

### 修法

```cpp
// net_socket.hpp —— 必须在包含 <winsock2.h> 之前
#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef FD_SETSIZE
#define FD_SETSIZE 8192          // 或与 max_clients 上限匹配的值
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/select.h>
#endif
```

**命令行 `-DFD_SETSIZE=64` 是用来"复现旧行为"的**（见 `app-host-load-acceptance` 的负向对照），
**不是**用来验证修法的；上面那个 `#ifndef` 保护让"复现"与"修复"能共用同一份源码，正是为此。

同时让"集合"说真话，别再把静默变默认：

```cpp
class SocketSet {
 public:
  static constexpr std::size_t capacity() noexcept { return FD_SETSIZE; }

  /// 返回是否真的存进去了。调用方必须检查。
  bool add(SocketHandle h) noexcept {
    if (h == kInvalidSocket) return false;
    if (count_ >= capacity()) return false;      // Windows：FD_SET 会静默丢，这里改成如实报告
#if !defined(_WIN32)
    if (h >= FD_SETSIZE) return false;           // POSIX：越界是写栈 UB，必须先拦
#endif
    FD_SET(h, &set_);
    ++count_;
    ...
    return true;
  }
 private:
  std::size_t count_ = 0;    // 不要用 fd_count：POSIX 没有这个字段
};
```

> **两处都不能省**：Windows 侧不拦就是静默丢数据；POSIX 侧不拦是**内存破坏**。
> 用自维护的 `count_` 而不是 `fd_count`，代码才能在两个平台同一份。

---

## 2 · 致命二：`listen` 套接字**也必须**非阻塞

`select()` 报告"有待接受连接"与套接字是否阻塞**无关**。所以阻塞 `accept()` 看起来完全正确
—— 直到 backlog 排空后的**第二次**调用永久挂在那里（再也没有下一个连接来唤醒它）。

**症状**：能接受连接一阵子，然后**再也没有新客户端能进**；`select()` 一直在报"有连接"。
排查线索：把逐层诊断打开，会看到 `ready=1 contains=1` 之后日志**停在某一轮不再前进**。

修法：`bind()` 里顺手把监听套接字设成非阻塞：

```cpp
listener.bind(...) {
  set_non_blocking(socket.native());   // 与客户端套接字同一处理
  ::listen(socket.native(), backlog);
}
```

---

## 3 · 致命三：`backlog` 必须覆盖"一个 tick 内到达的连接数"

`backlog` 是**内核**的"已建立但未 `accept()`"队列。服务每 `poll_interval_ms` 才批量排空一次。
若两次 tick 之间到达的连接多过队列容量，**内核在服务之前**就拒绝 ——
`max_clients` 根本轮不到被检查。

实测（单线程 `select()`，`poll_interval_ms: 5`，1000 个**同时**连接）：

| backlog | 被拒连接数 | 备注 |
|---|---|---|
| 16（曾经的默认） | **63** (`WSAECONNREFUSED 10061`) | 全部在 accept 之前被内核拒掉 |
| 128 | 0（0.56 s） | 可用 |
| 512 | 0（0.17 s） | 更快排空 |

⇒ **默认值要按"预期突发规模"给**，不是按"稳态并发"。并把这条做成启动期告警：

```
[relay] watch ceiling : 8191
[relay] max clients  : 1000
[warn] backlog=16 is below max_clients=1000; a connect burst larger than the
       kernel pending queue will be refused before the server can accept it
```

同一个服务里有三个容量概念，**别混**：

| 概念 | 谁的限制 | 溢出后果 |
|---|---|---|
| `backlog` | 内核待接受队列 | 连接被拒（RST / `ECONNREFUSED`） |
| 等待集合容量（`FD_SETSIZE`） | 库 / 平台 | **静默丢数据**（Windows）/ UB（POSIX） |
| `max_clients` | 你自己的策略 | 服务主动拒绝并告知 |

---

## 4 · 运维契约：**服务自身的输出必须是纯 ASCII**

`std::system_category().message(code)`（以及 POSIX 下等价的 `strerror`）是**本地化**的 ——
返回的是**控制台代码页**文本，不是 ASCII。

实测（中文 Windows / cp936）：对端 RST 断开时，一行 `[warn] recv ... failed:` 后面会跟
**34 字节 GBK 中文**（"远程主机强迫关闭了一个现有的连接。"）。规模越大（批量断开）越严重，
而且对任何**按 UTF-8 读日志**的消费者都是非法字节 —— 日志采集器、CI 断言、管道全部会崩或乱码。

**修法：固定名称表 + 数字码**，永不调本地化 API：

```cpp
std::string last_socket_error_text() {
  const int code = last_socket_error_code();
  const char* name = "socket error";
  switch (code) {
    case WSAECONNRESET: name = "WSAECONNRESET"; break;
    case WSAECONNREFUSED: name = "WSAECONNREFUSED"; break;
    ...
  }
  return std::string(name) + " (code " + std::to_string(code) + ")";
}
```

`getaddrinfo` 的 `gai_strerror()` **同理**，也要换名称表。

> 这是一条通用契约，不只是显示问题：**只要日志要被程序消费（CI、脚本、采集器），
> 它的稳定字节序就是接口的一部分。** 想输出中文就把控制台代码页显式设为 UTF-8，
> 并把它当作一个**显式的、有意的**变更，而不是让它随 `LC_ALL` 漂移。

---

## 5 · 把静默变响亮：容量单一真值源

静默截断能活很久，是因为**没人报告它**。三条改动把它变成响亮的事实：

1. **单一真值源**：`effective_max_clients() = min(max_clients, capacity() - 1)`
   （减 1 给监听套接字），**accept 路径与拒绝文案都用它**，绝不各写一份。
2. **启动打印真实上限**：`[relay] watch ceiling : <N>`。
3. **越界进计数**：`poll_set_overflows`（等待集合溢出次数）进 `stats` 行 ——
   一旦非 0，就是"有数据被丢"，而不是"看起来正常"。

外加两条启动期告警：`max_clients > 容量`、`backlog < max_clients`。

> 注意 `poll_set_overflows` 可能在当前配置下**不可达**（例如容量 8191 > `max_clients` 上限 4096）。
> 这是**刻意的纵深防御**：将来有人把 `max_clients` 上限调大而没动 `FD_SETSIZE` 时它会立刻说话。
> 别因为"计数恒为 0"就删掉它，要在注释里写明为什么保留。

---

## 6 · reactor / room 双任务：给"没有 I/O 就绪原语"的协作式调度器补 I/O

若底层是一个**纯协作式**事件循环（只有定时器 / 事件 / 通道 / 取消，**没有 epoll/select 集成**），
`select()` 必须由你自己接进去。可行且清晰的拆法是**两个任务**：

```
reactor_task                                  room_task
------------                                  ---------
只碰 socket                                    只碰协议 + 名册 / 扇出
select() → accept/recv → 推 InboundEvent  ───▶  Channel<InboundEvent>::receive()
每轮无条件 co_await sleep_for(poll_interval)
```

四条 load-bearing 的细节：

1. **reactor 必须每轮无条件让出。** "过期 deadline 的 `sleep_for` 只是取消检查点，不必然挂起"
   —— 所以"只在空闲时让出"会让 room_task **永远拿不到调度**。
2. **事件要自带它需要的一切快照。** 事件在被读取的那一刻就把连接标签（以及当时的昵称之类）
   带上，因为等 room 处理一条 `Left` 时，客户端的 socket 记录可能已经不存在了。
3. **单消费者通道换来 FIFO 顺序。** `Channel<InboundEvent>` 的单消费者顺序正是运行时保证的，
   不要引入第二个消费者。
4. **"快照 vs 名册为准"要选边。** 典型坑：一次 `recv()` 会把"改昵称命令 + 后续行"**同一批**
   读走，两条事件都带**旧**昵称 ⇒ 回复显示错名字。**属主是 room**：room 侧一律从名册解析，
   事件快照仅作"客户端已离场"时的回退。

---

## 7 · 一包 = 一次 `send()`：尽量保边界，但边界是 best-effort

- 输出用 **`deque<Packet>`** 而不是一个字节缓冲：转发时**一包一次 `send()`**。
  先拼成一个流再发，会在"其实能保住边界"的情况下也把边界丢掉。
- 但 **TCP 是流**：对端 `recv()` 仍可能把两个包合并。**字节内容与顺序有保证，边界没有。**
  需要帧边界就自己加长度前缀（服务会原样透传）。
- 由此推出两条**测量纪律**（详见 `app-host-load-acceptance`）：
  - 断"包边界"必须**给发送方加节奏**（发一个 → 等对端收到 → 再发下一个）；
  - 断"字节相等"可以**无条件**。
  把两类断言混在一起来写，会得到"测的是内核行为、不是服务行为"的假结论。

---

## 8 · 优雅关闭：detach 的控制台线程会把 `exit()` 锁死

`stdin` 命令线程如果 `detach()` 着，它多半正阻塞在 `std::getline` 里并**持有流锁**。
`return` 出 `main()` 后进程在**拆除标准流**时与之互锁 ⇒ **进程不退出**。

取证方式（很干净）：

```
stdin 保持打开  -> 退出超时（挂死）
stdin 已关闭    -> 退出码 0
```

修法：走完优雅路径后**显式**终结：

```cpp
console.detach();
std::fflush(stdout);
std::_Exit(0);        // 不走标准流拆除
```

前提是"每个日志行写时就已刷出"，且 detach 的线程只持有 `shared_ptr`（不留悬垂）。
Windows 上把 `stdout/stderr` 设成二进制模式（`_setmode(_fileno(stdout), _O_BINARY)`），
否则 CRT 会悄悄改写行尾 —— 对一个字节透传服务是致命的。

---

## 9 · 零依赖配置子集：**拒绝**，而不是半应用

要"零第三方依赖"时，自己写一个小配置读取器是合理的。关键判据是**失败形态**：

| 错误类型 | 正确行为 |
|---|---|
| 拼错键名 `prot: 12333` | `unknown configuration key(s): 'server.prot'`（**不是**静默用默认值！） |
| 重复键 | `duplicate key 'server.port' (first defined on line N)` |
| 制表符缩进 | `tabs are not allowed for indentation (use 2 spaces)` |
| 子集之外的语法（序列/锚点/多行标量/第二文档） | **带行号**报错，绝不"应用了一半" |

- 支持范围要写在文档里（`#` 注释、空行、`---`/`...`、缩进嵌套、单双引号 + 转义、裸标量、
  `true/false/yes/no/on/off/1/0`）。
- **`port: 0` 要合法**（向 OS 要临时端口）—— 否则多个实例与自动化测试无法并存。
  范围是 `[0, 65535]`，不是 `[1, 65535]`。
- **样例配置文件与内置默认模板必须逐字同步**，并且**用测试守卫**（比对两者的键与值）。
  根因提醒：改了默认模板后只增量重建了"测试目标"而没重编服务，会看到
  `--print-default-config` 打出旧模板 —— **按 target 增量构建时，改了共享源文件必须全量重建**。

---

## 参考
- [`references/fdset-and-select-limits.md`](references/fdset-and-select-limits.md) — `FD_SET` 截断的完整取证
  过程、跨平台差异、探测脚本用法、容量与 `max_clients` 的关系
- [`references/error-text-and-ascii-contract.md`](references/error-text-and-ascii-contract.md) —
  本地化错误的取证与 ASCII 名称表写法，其它"隐式本地化"来源
- [`references/config-subset-parser.md`](references/config-subset-parser.md) — 零依赖配置子集的判据、
  同步守卫、启动期告警清单
- [`references/launcher-and-build-tree.md`](references/launcher-and-build-tree.md) — 一键脚本的三个
  平台坑：构建树按平台分开、`set /a` 回绕校验、日志尾部输出
- [`scripts/probe_fdset.c`](scripts/probe_fdset.c) — 一条命令测出本平台的 `FD_SETSIZE` 与截断行为
