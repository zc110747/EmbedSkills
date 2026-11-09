---
name: windows-shell-traps
description: Windows 脚本与文件操作的静默失败：bat 裸括号、沙箱跑 .bat、追加重定向截断、.gitignore 吞源文件、file-history 恢复。
agent_created: true
---

# Windows 脚本 / 文件操作的静默失败

Windows 上最贵的 bug 不是报错，是**没有报错**：退出码 0、目录看着正常、日志里有你 grep 的关键字，
但事实与结论相反。本篇按"静默"这条主线收口：批处理语法、沙箱里跑 `.bat`、写文件、
`.gitignore` 吞源文件，以及事后恢复。

## 何时用

- `.bat` 报 `此时不应有 or` / `此时不应有 .`，或在 preflight 就死、业务输出一行没有。
- 需要在沙箱/CI 里**真跑** `.bat`，而 Bash / PowerShell 工具都拦 `cmd.exe`。
- 同一命令在不同 shell 里表现不一致，或 PowerShell 返回 0 却没有输出。
- 追加写文件后**内容看着在、开头却丢了**。
- 「我没删过它，但 clone 下来就没有」/「本机能编，别人编不过」。

## 一、三条观测纪律（先做这个，再排任何故障）

1. **退出码不是证据**。判据是"被观测对象自己的产物"：脚本 banner、输出文件、端口监听、
   文件长度、用例收集数。`exit 0` 只说明解释器没崩。
2. **日志里有这段文字 ≠ 这段代码执行过**。批处理回显、注释、`rem` 行都会命中 `grep`
   ⇒ 判定要锚在**变量展开结果**或**只有该分支才产生的副作用**上。
3. **先怀疑取证工具，再怀疑被测对象**。同名程序被系统版顶包、`cmd //c` 静默空跑、
   重定向不落文件，都会造出"不可能的症状"（如计数翻倍、重复执行）。

## 二、批处理语法：括号与 trace

| 判据 | 结论 |
|---|---|
| 块内裸括号 | `if (...)` / `for (...)` **块内** echo 的裸 `)` 会**提前闭合块**，余下文本成游离 token；报错内容取决于残留文本（`or` / `.` 都可能），常死在 preflight |
| 哪些括号安全 | 同一行**双引号内**的括号安全；**顶层**（不在任何块内）的括号安全。别"见括号就慌"，按位置判 |
| 块内 `>` | 会被当成**整块**的重定向 ⇒ 写文本一律 `^>` |
| 定位手段 | 把首行 `@echo off` 换成 `@echo on`，并把 `pause` / `start` 整行 `rem`，trace 会停在出错行。探针脚本必须放**原脚本同目录**（`%~dp0` 决定工程根，换目录会走到另一个分支，追出假现场） |
| 读 trace | `@echo on` 会回显**未被选中**的分支 ⇒ 被选中的分支同一句出现 **2 次**（源回显 + 实际输出），未选中的只有 **1 次**。别按"日志里有这段"下结论 |
| `start` 行 | 不能改成 `echo`（行内 `&&` 会被当命令分隔符真的执行），只能整行 `rem`；块里留 `rem` 不算空块，解析正常 |
| 假阳性 | 错误文本可能出自 `rem` 注释行 ⇒ 判定语法错误要**排除 `rem` 行**，不要全文 grep |

## 三、在沙箱里真跑 `.bat`

| 入口 | 结果 |
|---|---|
| Bash 工具 `cmd.exe /c x.bat` | ❌ 被拦（"bypasses command validation"） |
| Bash 工具 `cmd //c "..."` | ❌ 只打 cmd 横幅就退出（MSYS 路径转换吞命令），且**重定向到 `/tmp` 不落文件** |
| PowerShell 工具 `cmd /c` | ❌ 被拦 |
| **Python `subprocess.run(['cmd','/c', ...])`** | ✅ 唯一可靠路径 |
| Bash 工具里跑 `npx <tool>` | ❌ 触发 `wsl.exe` 黑名单，stdout 变二进制噪声 ⇒ 易误判成"命令炸了"。绕开 npx，直接跑包内 CLI |

两个必踩的坑：

- **`capture_output=True` 会在子进程 detach 时永久挂起**：`start "..." cmd /k ...` 拉起的进程
  继承了管道句柄，即使 launcher 已 `exit /b 0`，`communicate()` 也等不到 EOF。
  ⇒ **重定向到文件**，不要用管道；stdin 给 `DEVNULL`（`pause` 遇 EOF 即返回）。
- **工具调用结束时整个进程树被回收**：`start` 拉起的服务活不过本次调用。
  症状自相矛盾——launcher 的 `/healthz` 报 OK，下一次调用里端口全空。
  ⇒ **起服务与验证必须在同一次调用内**：一个 Python 编排脚本串完"起 → 探活 → 断言 → 按端口找 PID 收尾"。

> 看到"探针 OK 但端口是空的"，先想到进程树被回收，别判定"服务起不来"——两个结论完全不同。

## 四、工具被系统版顶包（Windows + Git Bash）

| 你以为 | 实际 | 症状 / 规避 |
|---|---|---|
| GNU `find` | `FIND.exe` | 报"参数格式不正确" ⇒ 用 Glob / Grep 工具或 Python `os.walk` |
| GNU `sort -u` | `sort.exe` | **静默返回空** ⇒ bash 里用 `case` 判重 |
| GNU `timeout` | `timeout.exe` | 报"默认选项不允许超过 1 次" ⇒ 限时在 Python/Node 里做 |
| `tasklist \| grep` | 管道不稳定 | 常常什么都匹配不到 ⇒ `tasklist /FO CSV /NH` 写文件再筛 |
| `taskkill /PID` | `/X` 被 MSYS 当路径 | `MSYS_NO_PATHCONV=1` 前缀 |
| PowerShell 工具 | 吞子进程 stdout | 返回 0 但无输出 ⇒ 结果写文件再 Read |

`cmd //c "… > /tmp/x.log"` 的路径 MSYS 不认 ⇒ 之后 `grep` 读到的是**旧文件堆积**，
能造出"重复执行 / 计数翻倍"这类不可能的症状。给 cmd / PowerShell 的路径必须是 `%TEMP%` 或 `C:\...`。

## 五、写文件：追加重定向会截断

`cat >> file <<'EOF'` 在本环境可能**从偏移 0 覆盖**：退出码 0、无报错、`grep` 新内容还能命中，
只有**文件长度不变**能看出来。

- 判定：追加前后比 `stat -c%s`，**没变大 = 中招**。
- 正确做法：一律用 Write / Edit 工具；必须追加时用 Python 二进制 `open(...,'ab')` 并断言 size 增长。
- 同一文件的两处 Edit 不要放同一条消息（并行会互相覆盖，其中一处被静默吞掉）；改完要复核。
- 用 `old_string` 命中标题行时，新内容里要把标题补回去，否则标题被吃掉。

## 六、git 静默吞源文件

两个设计叠加：`.gitignore` 是**全局通配**匹配；`git add` 遇到被忽略路径是**静默 no-op**（退出码 0）。
最恶性的后果是"**一半提交**"：同目录下只吃掉一个文件，作者本机因为文件还在磁盘上一切正常，
**任何一次重新 clone 都编译全挂**。

三步定位：

```bash
git check-ignore -v path/to/file                                   # 有输出 = 被忽略，并给出规则文件:行号
git log --all --diff-filter=A --name-only -- '**/file'             # 无输出 = 从未 add 成功，不是"被误删"
git status --ignored --short | grep '^!!'                          # 同类还有哪些
```

修复：补回文件 → 改 `.gitignore` 并把"为什么不能再加回来"写进注释（否则下一个人顺手再加）→
`git check-ignore -v` 必须**无输出**且 `git status --short` 能看到 `??` / `A`。

判据：**重新 clone 到临时目录能否构建**。"本机能编过"恰恰是这个 bug 的默认状态，证明不了任何事。

## 七、恢复通道

- **文件被写坏**：先别重写。`~/.workbuddy/file-history/<project-uuid>/<hash>@vN` 是逐版本快照；
  用特征串 `grep -rl` 定位，用**原始字节数**对齐版本号，校验 UTF-8 可解码 + 关键锚点齐全再覆盖回去。
- **要复现历史构建结果**：`git archive <rev>^ <subdir> | tar -x -C $TMP` 后原样重编，
  比推理"大概是编译器漂移"硬得多；`git archive` 不碰仓库元数据，比 `git worktree` 更适合"只量一个旧数字"。
  必须**整个子目录一起导出**（脚本靠 `%~dp0..` 定位工程根）。

## 反模式

- 用退出码 0 / "命令完成"当成功。
- 用 `grep` 命中当"分支执行过"。
- 把 `capture_output=True` 用在会 detach 的 launcher 上。
- 把"起服务"和"验证"拆成两次工具调用。
- 用 `sed -i` 改 CRLF 文件（会剥掉行尾）。
- 用 `rm -rf` / 循环串多个目录做清理（沙箱会 SIGTERM）⇒ `find <dir> -depth -delete`，一次一个目录。
- 新建目录 / 新增文件类型时不做探针：`git check-ignore -v <新路径>/probe.txt`。

## 详细资料

- `references/bat-syntax-traps.md` — 括号安全判定表、`@echo on` trace 全套操作与三个反直觉点。
- `references/sandbox-run-bat.md` — Python `subprocess` 真跑、防挂起、进程树回收、PowerShell 等效复刻、PATH 注入、cmd 引号与结构复刻。
- `references/shell-append-truncation.md` — 追加重定向截断的实测、Python 二进制追加、file-history 恢复步骤。
- `references/git-ignored-sources.md` — 机制、三步定位、`.gitignore` 修复与类案清单（`*.mod`/`Build/`/`third_party/` 等）。
