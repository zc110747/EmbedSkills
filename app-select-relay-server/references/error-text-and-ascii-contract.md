# 错误文本的本地化 · "输出纯 ASCII" 契约

配套 `app-select-relay-server/SKILL.md` §4。适用范围远超 socket：**任何要被程序消费的日志。**

---

## 一、取证过程（三步，别跳第 3 步）

### 1. 先量字节，不要靠眼睛看

先用 Python 抓被测进程的原始 stdout，统计非 ASCII 字节：

```python
out = proc.stdout_bytes()          # 原始 bytes，不要先 decode
bad = [b for b in out if b > 0x7F]
print("non-ascii bytes:", len(bad), bad[:16])
```

发现：正常路径 **0 个非 ASCII 字节**；但一次**大规模突发断开**之后，日志里出现了 `0xb3` 之类的字节。

### 2. 定位到"哪一行"

把出问题的行取出来（`od -c` 或 Python 逐行 `repr`），会看到：

```
[warn] recv from 127.0.0.1:51820 failed: <34 bytes of non-ascii>
```

### 3. 用**原始字节**还原它说的是什么

```python
line.encode('latin-1').decode('gbk')     # 中文 Windows 的代码页是 936
# -> '远程主机强迫关闭了一个现有的连接。'
```

⇒ 这正是 **WSAECONNRESET (10054)** 的**本地化**文本。根因：

```cpp
std::system_category().message(code)    // ← 返回控制台代码页文本，不是 ASCII
```

---

## 二、为什么它是**真缺陷**（而不是"日志里有点中文而已"）

| 消费者 | 后果 |
|---|---|
| 采集器 / CI 断言（按 UTF-8 解码） | 非法字节 → 抛异常 / 替换成 `?`，一行坏掉可能整段丢掉 |
| 管道给下一个程序 | 同上 |
| 规模效应 | 断开越多、坏行越多。**突发断开正是你最需要日志的时候** |
| 契约一致性 | README 写着"服务自身输出为 ASCII"，实际不是 —— 契约失效比乱码更糟 |

---

## 三、修法：固定的 ASCII 名称表 + 数字码

```cpp
std::string last_socket_error_text() {
  const int code = last_socket_error_code();
  const char* name = nullptr;
  switch (code) {
#if defined(_WIN32)
    case WSAECONNRESET:   name = "WSAECONNRESET";   break;
    case WSAECONNREFUSED: name = "WSAECONNREFUSED"; break;
    case WSAENOTCONN:     name = "WSAENOTCONN";     break;
    case WSAEWOULDBLOCK:  name = "WSAEWOULDBLOCK";  break;
#else
    case ECONNRESET:      name = "ECONNRESET";      break;
    case ECONNREFUSED:    name = "ECONNREFUSED";    break;
    case ENOTCONN:        name = "ENOTCONN";        break;
    case EAGAIN:          name = "EAGAIN";          break;
#endif
    default: break;
  }
  return (name != nullptr)
       ? std::string(name) + " (code " + std::to_string(code) + ")"
       : std::string("socket error (code ") + std::to_string(code) + ")";
}
```

要点：

- **`default` 分支必须保留数字码** —— 名称表永远不全，数字码是最后的真相。
- 返回 `"WSAECONNRESET (code 10054)"` 这种形态：既可读、又**可以被脚本 grep 到稳定字符串**。
- 顺手验证：改完重跑取证脚本，非 ASCII 字节数应为 **0**。

### 同族的其它"隐式本地化"

| 调用 | 问题 | 替代 |
|---|---|---|
| `std::system_category().message()` | 控制台代码页 | 名称表 + 数字码 |
| `gai_strerror()` / `gai_strerrorA()` | 同上 | 名称表（`EAI_AGAIN` / `EAI_NONAME` / …） + 数字码 |
| `strerror()` | 同上 | 同上 |
| `FormatMessage(FORMAT_MESSAGE_FROM_SYSTEM)` | 系统语言 | 同上 |
| `GetLastError()` 文本化 | 同上 | 只打数字码 |

**顺带清理**：把 `#include <system_error>` 删掉（如果它是唯一使用者）—— 让"不依赖本地化"
这件事在编译期可见，而不是靠 reviewer 记住。

---

## 四、这条契约的**通用**表述（值得写进任何服务的 README）

> **服务自身的输出 = 契约的一部分。**
> 只要它会被程序消费（CI、脚本、采集器、管道），它的稳定字节序就是接口。
> 因此：
>
> 1. 默认输出 **ASCII**（可 grep、可比较、与代码页无关）；
> 2. 交付 payload / 用户数据**原样透传，绝不检查**（那是另一条契约）；
> 3. 想输出本地化文本时，**显式**把控制台代码页设成 UTF-8，并把它当成一次**有意的变更**
>    记进 diff —— 而不是让它随 `LC_ALL` / 系统语言漂流。

> 这条与"透传服务的字节透明性"是**两条独立的契约**，别混：
> 服务自己写出的字节（日志 + 少量控制通知）必须**稳定、ASCII**；
> 客户端之间流传的字节必须**原样、不解释**。
> 前者可 grep、可断言；后者可承载任意二进制。

---

## 五、一条对应的测试（防止回归）

在验收脚本里加一条**廉价但有效**的守卫：把服务整个生命周期（含**故意制造大批量连接重置**）
的 stdout/stderr 全量收集，断言 `all(b < 0x80 for b in output)`。

- 这条测试在"只有正常路径"时**恒为真**，必须有**突发断开**场景才有效；
- 所以它要挂在**规模/压力场景**里（见 `verification-and-acceptance`），不是挂在"连两个客户端"的场景里。
