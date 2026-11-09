# 批处理语法陷阱与 `@echo on` trace

## 1. `echo` 内的 `)` 在 `if`/`else` 块内提前闭合

```bat
if %errorlevel% neq 0 (
  echo Install tool from https://example.com/dl, or run scripts\setup.bat.
) else (
  echo ok
)
```

`echo` 行 URL/说明里的 `)` **提前终止了外层 `if` 块**，剩余文本变成块外 token，
cmd 报 `'此时不应有 or'`（`or` 成了意外 token）。

修法（按稳妥度）：

1. 改写 echo，不带任何括号：`echo Install tool from https://example.com/dl, or run scripts\setup.bat.`
2. 用 `^)` 转义：`echo Install tool from https://example.com/dl^) ...`
3. 整句包成独立块时，确保括号配对且不在引号/URL 里被夹断。

### 哪些括号安全（逐项实测，别"见括号就慌"）

| 位置 | 安全? | 说明 |
|---|---|---|
| `if (...)` / `for ... (...)` **块内** echo 里的裸 `(` `)` | ❌ 炸 | 块读取器扫到第一个 `)` 就闭合块，余下文本成游离 token |
| 同一行**双引号内**的括号 | ✅ | 引号保护，块内也安全 |
| **顶层**（不在任何块里）echo 里的括号 | ✅ | 不参与块配对 |

症状不止 `or`：块内裸 `)` 之后残留什么就报什么，实测另一种是 `echo ... the model truth (package).`
⇒ `此时不应有 .`，`RC=255`，而且**死在 preflight，业务输出一行都没打**。

块内 echo 里的裸 `>` 同理会被当成**整块**的重定向 ⇒ 写文本用 `^>`。

## 2. 定位：`@echo on` trace

比逐段二分快得多：把首行 `@echo off` 换成 `@echo on`，并把 `pause` / `start` 行注释掉
（免得真起进程）。

```python
src = open('x.bat', encoding='utf-8').read().split('\n')
src[0] = '@echo on'
out = ['rem ' + l if l.strip().lower().startswith(('pause', 'start "')) else l for l in src]
open('_trace_probe.bat', 'w', encoding='utf-8', newline='\r\n').write('\n'.join(out))
```

跑 `_trace_probe.bat`，trace 会停在出错行，stderr 给出错误文本。

⚠️ **探针脚本必须与原脚本同目录**：`.bat` 里的 `%~dp0` 决定工程根，放到别处会让 preflight
走错分支（实测放到捕获目录时 `%~dp0` 变了 ⇒ 直接报"binary missing"，追出来的是假现场）。

## 3. 读 trace 的三个反直觉点

1. **`@echo on` 会回显「未被选中」的 if 分支整块。**
   日志里会同时出现两个分支的内容文本，乍看像"都执行了"。
   **判据：数重复次数。**
   - 被选中的分支 ⇒ 源回显 + 实际输出 ⇒ 同一句出现 **2 次**
   - 未选中的分支 ⇒ 只有源回显 ⇒ **1 次**
   更硬的锚点：选一个"只有该分支才会打印的**变量展开结果**"。
2. **`start "..."` 那行不能改成 `echo`，只能整行 `rem`。**
   行里有 `&&` 与成对引号（`cmd /k "set A=1&& set B=2"`），用 `echo` 打出去会被 cmd
   把 `&&` 当**命令分隔符**，真的执行后半段。`rem` 整行注释的副作用是
   `if exist (...) else (...)` 两侧都成注释，但块里仍有 `rem` 语句、**不算空块**，解析正常。
3. **错误文本可能出自 `rem` 行**（例如某行注释正文就在讲这个坑）。
   ⇒ 判定语法错误要**排除 `rem` 行**，不要拿全文 `grep` 当判据。

## 4. 其他易踩

- 块内 `echo` 里的 `(` `)` 与 `>` 都要按上表判；写文本一律 `^>`。
- `.bat` 里的中文/特殊字符要确认代码页；输出重定向时 `chcp` 会影响写出的编码。
- `pause` 只留给双击启动器，**管道/`for` 循环里出现 `pause` 会永久挂住**。
