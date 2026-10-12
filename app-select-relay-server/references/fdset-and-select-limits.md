# `FD_SET` 截断 · `select()` 的容量 · 取证与修法

配套 `app-select-relay-server/SKILL.md` §1–§3。

---

## 一、取证（五步，每步都可复现）

### 1. 测出本平台的容量

```bash
# Windows / MinGW-w64
gcc -O2 -std=c11 probe_fdset.c -o probe_fdset.exe -lws2_32 && ./probe_fdset.exe
```

实测输出（MinGW-w64 / GCC 15.2 / Windows）：

```
FD_SETSIZE          = 64
sizeof(fd_set)      = 520 bytes      # 64 * 8 字节句柄 + 8 字节计数
sizeof(handle)      = 8 bytes
requested  = 128
stored     = 64                      # ← 后 64 个被静默丢弃
fd_count   = 64
[!] FD_SET SILENTLY TRUNCATED 64 of 128 handles.
```

同一探针在 `-DFD_SETSIZE=8192` 下：`FD_SETSIZE=8192`、`sizeof(fd_set)=65544`、
`requested=128 → stored=128`。**修法与复现共用同一个探针**，这就是它值得留在手边的原因。

### 2. 用真客户端定位"从第几个开始失效"

起一个 100 客户端的真实场景，让**不同索引**的客户端各发一个带唯一标签的包，统计有多少人收到：

```
发送者  0 号 -> 99/99 收到
发送者 50 号 -> 99/99 收到
发送者 62 号 -> 99/99 收到
发送者 63 号 ->  0/99 收到      ← 边界在这里
发送者 64 号 ->  0/99 收到
发送者 80 号 ->  0/99 收到
发送者 99 号 ->  0/99 收到
```

边界恰好 = `FD_SETSIZE`（63 个客户端 + 1 个监听）。

### 3. 确认"截断"而不是"拒绝"

再看服务端计数：`accepted` / `online` 都等于 100，`rejected == 0`，**没有任何错误日志**。
⇒ 连接是成功的，被吞掉的只是**读**。

### 4. ⚠️ 确认你没有被"扇出不过 `fd_set`"骗到

如果服务是"收到一个包就抄送全表"的结构，高位客户端**收得到**别人的包。
所以它表现为"**单边失聪**"：能收、不能发。**只用低位客户端做复现，会得出"没问题"的相反结论。**

### 5. 上规模再确认一次

100 / 300 / 500 / 1000 客户端下，`packets_out` 是否精确等于 `发送者数 × (N − 1)`。
修复前这个恒等式**在生产规模下会破**，而且破得很安静。

---

## 二、跨平台差异表

| | Windows / Winsock2 | POSIX / glibc |
|---|---|---|
| `FD_SETSIZE` 默认 | **64**（`winsock2.h` 里的默认值，可在包含前改写） | 1024（`__FD_SETSIZE`） |
| `fd_set` 表示 | 句柄**数组** + `fd_count` 计数 | 按**描述符下标**索引的位图 |
| 超出容量时 `FD_SET` | **静默丢弃**（`fd_count` 停住） | **越界写**（未定义行为，实测常为踩栈） |
| `select()` 首参数 | 忽略 | 必须给"最大描述符 + 1" |
| `count` 从哪来 | `set.fd_count` | 没有这个字段，必须自己维护 |

**结论**：包装类必须**自己维护 `count_`**，因为 POSIX 侧根本没有 `fd_count`；
`add()` 在 Windows 侧查容量、在 POSIX 侧查 `fd >= FD_SETSIZE`，两处都返回 `bool`。

---

## 三、修法（三处，缺一不可）

### 3.1 在包含 winsock2.h **之前**提升宏

```cpp
#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
// MUST come before <winsock2.h>
#ifndef FD_SETSIZE
#define FD_SETSIZE 8192
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/select.h>
#endif
```

**放在哪个头里很关键**：它必须是**所有**包含 winsock2.h 的翻译单元都会先走到的那个头
（例如统一的 socket 抽象层）。漏了一个 TU 就会那个 TU 是 64、其它是 8192 —— 这类
"两套 ABI 混合"比单纯崩掉更难查。**改完用 `grep -n "winsock2.h"` 逐个 TU 核对包含顺序。**

### 3.2 `add()` 如实报告

```cpp
bool SocketSet::add(SocketHandle h) noexcept {
  if (h == kInvalidSocket)         return false;
  if (count_ >= capacity())        return false;     // Windows：FD_SET 会静默丢
#if !defined(_WIN32)
  if (static_cast<std::size_t>(h) >= capacity()) return false;  // POSIX：越界是写栈
#endif
  FD_SET(h, &set_);
  ++count_;
  if (highest_ == kInvalidSocket ||
      static_cast<std::uint64_t>(h) > static_cast<std::uint64_t>(highest_)) {
    highest_ = h;
  }
  return true;
}
```

调用方**必须**检查返回值并把溢出计数上抛（`poll_set_overflows`），否则等于什么都没修。

### 3.3 用"有效上限"这一个真值源

```cpp
std::size_t effective_max_clients(const Settings& s) {
  const std::size_t ceiling = SocketSet::capacity() - 1;   // 减 1 = 监听套接字
  return std::min<std::size_t>(s.server.max_clients, ceiling);
}
```

**accept 判断与"服务器已满"的拒绝文案都用它**。两处各写一份是这类 bug 的经典复发口。

---

## 四、`sizeof(fd_set)` 变大的代价（为什么不是"越大越好"）

`FD_SETSIZE=8192` ⇒ `sizeof(fd_set) = 65544` 字节。每一轮 poll 都会：

- `FD_ZERO`：把 64 KB 清一遍；
- 逐个 `FD_SET`：Windows 侧是**线性查重**（O(n) 每次），填 n 个句柄即 O(n²)；
- `select()` 内核拷贝 64 KB。

实测（1000 客户端、5 ms 轮询、Windows）：空闲 CPU **< 5%**，说明这个规模下不是瓶颈。
但要知道它的形状：

- 每轮成本 ≈ O(容量 + n²) 的查重 + 64 KB memset ⇒ **n 上千且轮询很快时，O(n²) 查重先成为瓶颈**；
- 再往上（数千～上万并发）就该换 `poll` / `epoll` / `kqueue` / IOCP —— 那时 `fd_set`
  的固定位图语义本身就是错的抽象。

> 判断标准：**不要因为"1000 客户端 CPU 还很低"就认定"规模问题已解决"。**
> 已证明的是"这个规模够用"，未证明的是"再大也够用"。

---

## 五、其它同类静默截断（同族要一起查）

`FD_SET` 的教训可以外推：**任何"固定容量 + 静默丢弃"的 API 都是同一类 bug**。

| API / 结构 | 静默失败的形态 |
|---|---|
| `FD_SET` | 满了不存，不报错 |
| `WSAEventSelect` 的事件位 | 未注册的事件类型永不报告 |
| 固定长度的环形缓冲 | 写满即覆盖或丢弃，计数不反映 |
| `snprintf` 的返回值 | 作者常忘记"返回值 ≥ size 表示被截断" |
| 非阻塞 `send` 的部分写 | 返回已写字节数，剩余必须自己排进待发队列 |

统一对策：**容量显式暴露 + 写入返回成败 + 溢出进计数**。三者缺一，静默就会再长出来。
