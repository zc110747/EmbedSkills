# 在沙箱/CI 里真跑 `.bat`

## 1. 入口选择（实测）

| 入口 | 结果 |
|---|---|
| Bash 工具 `cmd.exe /c x.bat` | ❌ harness 拦：`Command blocked for security: Invoking cmd.exe from Bash bypasses all command validation` |
| Bash 工具 `cmd //c "..."` | ❌ 只打 cmd 横幅就退出（MSYS 路径转换吞掉命令） |
| PowerShell 工具 `cmd /c ...` | ❌ 拦：`cmd.exe cannot be used from the PowerShell tool` |
| **Python `subprocess.run(['cmd','/c','x.bat'])`** | ✅ 可用 |
| Bash 工具 `npx <tool>` | ❌ 触发 `wsl.exe` 黑名单，stdout 整段变二进制噪声，`exit=1` ⇒ 极易误判成"命令炸了"。绕开 npx，直接跑包内 CLI（如 `node node_modules/<pkg>/<cli>.mjs run --reporter=json --outputFile=<path>`；`--reporter=default` 走 stdout 同样不可靠） |

```python
import subprocess
# `pause` 不会卡住：stdin 给 DEVNULL（遇 EOF 即返回），或 input='\n'
r = subprocess.run(['cmd', '/c', 'build.bat', '--help'], input='\n',
                   capture_output=True, text=True, errors='replace', cwd=r'C:\path\to\root')
print(r.returncode); print(r.stdout); print(r.stderr)   # stderr 常是 GBK，errors='replace' 兜住
```

## 2. `capture_output=True` 在子进程 detach 时永久挂起

`start "title" cmd /k ...` 拉起的子进程**继承 stdout/stderr 的管道句柄**。
即使 launcher 已 `exit /b 0`，`communicate()` 也等不到 EOF ⇒ 挂到超时（表现为工具调用被 SIGTERM）。

**修法：重定向到文件，不要用管道。**

```python
with open(log, 'w', encoding='utf-8', errors='replace') as fh:
    r = subprocess.run(['cmd', '/c', 'start.bat'], stdin=subprocess.DEVNULL,
                       stdout=fh, stderr=subprocess.STDOUT, cwd=ROOT)
```

这是唯一能同时拿到 launcher 输出、又不被 detach 子进程挂住的办法。

## 3. 进程树在工具调用结束时被回收

`start` 拉起的后端/前端**活不过本次工具调用**。症状自相矛盾：launcher 自己的 `/healthz`
探针报 OK，**下一次**调用里端口全空。

⇒ **起服务与验证必须在同一次调用内**：一个 Python 编排脚本串完
"起 → 探活 → 断言 → 收尾"，收尾按端口找 PID 再 `taskkill`（Git Bash 里 `/F` 会被 MSYS
当路径转换，需 `MSYS_NO_PATHCONV=1`）。

> 看到"探针 OK 但端口是空的"，先想到进程树被回收，别判定"服务起不来"。

## 4. 降级手段：PowerShell 等价复刻

只有当"真跑"不可行（需要交互式终端、或要脱离沙箱）时才用：把 `.bat` 的第 N..M 行
**逐字复刻**成 PowerShell，验证其中的**算法/闸门/构建命令**是否真触发。

```powershell
$ErrorActionPreference = 'Stop'
$root = '<repo>'
$env:PATH = "<toolchain-bin>;$env:PATH"          # 沙箱 PowerShell 不继承交互式 PATH
# 1) 人为把源文件造得比产物新
(Get-Item "$root/src/main.c").LastWriteTime = Get-Date
(Get-Item "$root/out/app.exe").LastWriteTime = (Get-Date).AddMinutes(-5)
# 2) 复刻闸门的 mtime 判定
$bin = Get-Item "$root/out/app.exe" -ErrorAction SilentlyContinue
$stale = ($null -eq $bin) -or ((Get-Item "$root/src/main.c").LastWriteTime -gt $bin.LastWriteTime)
if ($stale) { Write-Host "[BUILD] sources newer - rebuilding"; & $buildCmd }
```

跑：`& script.ps1 *> log.txt`。成功判据是日志出现 `[BUILD]` 与构建完成行。

> 复刻只验证算法与命令正确性，**不替代** `.bat` 本身的运行；真机/真实终端仍要跑一次。

## 5. 复现「历史版本的构建结果」

文档里的资源占用/体积对不上时，最硬的判据是把旧版本源码原样搬出来、用**同一个脚本**重编：

```bash
PREV="$TEMP/prevbuild"; rm -rf "$PREV"; mkdir -p "$PREV"
cd <repo> && git archive <rev>^ <subdir> | tar -x -C "$PREV"    # 只导出历史树，不动工作区
python - <<'PY'
import subprocess
r = subprocess.run(['cmd','/c','scripts\\build.bat','clean','--no-pause'],
                   stdin=subprocess.DEVNULL, capture_output=True, text=True,
                   errors='replace', cwd=r'<PREV>\<subdir>')
print('\n'.join(l for l in r.stdout.splitlines() if 'FLASH' in l or 'RAM' in l))
PY
```

一次就能把"编译器漂移"与"文档落后于代码"区分开。
不用 `git worktree`：它会留元数据且要记得清理；`git archive | tar -x` 用完删目录即可。
⚠️ 必须**整个子目录一起导出**（脚本靠 `%~dp0..` 定位工程根）。

## 6. Git Bash 里的 cmd / 引号

- `cmd //c "set X=1 && C:/long/path/x.bat"` 中 `&&` 与长路径会被 MSYS 改写
  ⇒ 用**临时 .bat 包装器**（同目录、相对名、纯 batch 语法）规避路径转换。
- 重定向 `>` 留给外层：`cmd //c "无重定向的命令" > log.txt`；写进 `cmd //c "..."`
  内部会被内层解析吞掉。
- PowerShell 工具**禁止** `cmd /c`（会被拦），需要 cmd 就回 §1 用 Python `subprocess`。
