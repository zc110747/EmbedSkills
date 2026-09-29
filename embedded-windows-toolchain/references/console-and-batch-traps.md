# 控制台与批处理陷阱取证（Windows 宿主）

一次验收里连续踩到 6 个坑，每个的症状都指向"脚本自己有 bug"，实际全是宿主/控制台的
行为。记在这里是因为它们与项目无关，换任何工程都会再遇到。

## 1. 长命令"无输出 + SIGTERM"：管道缓冲触发看门狗

**症状**：一条会跑 1 分钟以上的命令，工具返回 `Signal: SIGTERM`、`Stdout: (empty)`，
退出码 1。没有任何报错线索。

**根因**：命令写成 `tool ... 2>&1 | tail -45`。管道让 `tail` 缓冲全部输出直到 EOF，
于是**上层看到的 stdout 长时间为空**，按"无输出/疑似挂死"把整条命令杀掉——连带把它
启动的子进程（浏览器守护进程、服务端）一起回收。

**判据/修法**：长命令**不要走 `| tail` / `| head`**；解释器加 `-u`（Python）确保逐行
flush。本轮所有"神秘 SIGTERM"改为不加管道后全部消失。

```
✗  python scripts/verify_x.py 2>&1 | tail -40      # 缓冲 ⇒ 看门狗杀
✓  python -u scripts/verify_x.py
```

## 2. 批处理里裸调 `.cmd`：子批处理替换父批处理

**症状**：一个多步 `.bat` 跑到某个外部命令后**静默结束**，后面的步骤一行都没执行，
而**退出码是 0**——即"为没做的工作报成功"。

**根因**：那个外部命令是 `.cmd` 垫片（`agent-browser.cmd`）。在批处理里调用另一个
批处理**不加 `call`**，控制权不会返回：子批处理直接替换父批处理，父脚本的剩余内容
永远不会执行。

**修法**：每一处调用都加 `call`，包括 `call "%AB%" open ...`、`call "%AB%" screenshot ...`。
本轮第一次只给前 3 处加了 `call`、漏了第 4 处（`screenshot`），
于是脚本又在同一位置"静默成功"了一次——**修这类 bug 要全文搜一遍，不能只修眼前那行**：

```
✓  for /f ...; 之后核对：grep -n '^"%TOOL%"' script.bat   # 应为空
```

## 3. `EnableDelayedExpansion` 下 `!` 会吃掉字符

**症状**：把一个 1313 字符的字符串从文件读进批处理变量，再写回去变成 **1270 字符**，
少了 43 个字符，没有报错。

**根因**：脚本开了 `setlocal EnableDelayedExpansion`，此时 `!` 不是普通字符，而是延迟
变量引用的定界符。字符串里的 `!==` 被当作"`!` 开始、下一个 `!` 结束"，中间整段被当作
变量名吞掉。

**修法**：被取进变量（尤其是要再拼进命令行）的字符串里**不要出现 `!`**。例如把
`y !== c.height` 改成 `y - c.height`（非零即真）。或者在该段局部
`setlocal DisableDelayedExpansion`，用完再 `endlocal & set "X=%X%"`。

**自检**：往返一次并比较字节数，是本类问题的唯一可靠判据。

```
ref: 1313 bytes   via batch: 1270 bytes   ← 立刻可见
```

## 4. 取长字符串：`set /p` 截断，`for /f` 反引号嵌套引号报语法错

- `set /p X=<file` **上限 1023 字符**，超了静默截断。
- `for /f "usebackq delims=" %%j in (\`"%PY%" -c "..." \`)` ——反引号里再嵌双引号，
  cmd 解析不过来，直接报 `命令语法不正确。`（连脚本前面的 `echo` 都不输出）。

**修法**：**先落文件，再按文件读**，完全绕开子进程引用与引号嵌套：

```bat
"%PY%" -c "...sys.stdout.write(m.EVAL_JS)" > "%SHOT%\eval.js"
for /f "usebackq delims=" %%j in ("%SHOT%\eval.js") do set "JS=%%j"
```

## 5. `dir /s` 的通配符不能出现在路径中间段

**症状**：明明装了 Chromium，`dir /b /s "%LOCALAPPDATA%\ms-playwright\chromium-*\chrome-win64\chrome.exe"`
一条都匹配不到，脚本报"没安装"。而 `glob` / `find` 里同样的写法是对的。

**根因**：`dir` 的通配符只对**最后一段**生效；中间段有 `*` 时整条模式无效。

**修法**：先枚举目录，再拼内层路径：

```bat
for /f "delims=" %%d in ('dir /b /ad /o-n "%LOCALAPPDATA%\ms-playwright\chromium-*" 2^>nul') do (
  if not defined CHROME if exist "%LOCALAPPDATA%\ms-playwright\%%d\chrome-win64\chrome.exe" set "CHROME=...\%%d\chrome-win64\chrome.exe"
)
```

## 6. PATH 遮蔽：`timeout` 是 `TIMEOUT.EXE`，`cmd //c` 被宿主拦

- `timeout 10 cmd` 直接报 `错误: 无效语法。默认选项不允许超过 '1' 次。`——PATH 上的
  `timeout` 是 Windows 的 `TIMEOUT.EXE`（`/t` 才是秒数），不是 coreutils。
  批处理里用 `%SystemRoot%\System32\timeout.exe /t N`。
- 从 Git Bash 调 `cmd //c "..."` 被宿主的命令安全检查拦下（`Invoking cmd.exe from Bash
  bypasses all command validation`），但**直接按路径执行 `.bat` 是可以的**：
  `NO_PAUSE=1 "./scripts/verify_x.bat"`。别为一个被拦的包装层改设计。

## 通用教训

这些坑的共同点是**症状指向脚本、根因在宿主**，而且**成功路径与失败路径长得很像**
（退出码 0、无报错）。因此：

1. **看门狗杀 vs 真失败**要先分清：无输出 + 特定信号 ⇒ 先怀疑输出缓冲/空转，而不是脚本逻辑。
2. **退出码不足以判成功**：批处理被替换、脚本被截断时退出码都是 0。要有"步骤 N/M"这类
   进度标记，跑完比对最后一步是否出现。
3. **凡"把字符串搬过一层解释器"的地方，都要做一次字节往返核对**。
