# 主机侧 shell 与构建执行纪律

## 一、执行通道：谁跑长任务

本环境的 PowerShell 工具会**吞掉所有原生子进程的输出**：

- `& python.exe --version` → 空
- `Start-Process -RedirectStandardOutput ... -Wait` → 落文件 0 字节，`ExitCode` 为空
- `dangerouslyDisableSandbox: true` 也无效

但 **cmdlet 正常**（`Test-Path` / `Get-PnpDevice` / `Out-File` / `$PSVersionTable` 均有结果）。
所以"命令执行成功、exit 0" **不等于**子进程真的跑了。

开工前自查（10 秒）：

```powershell
& "C:\path\to\python.exe" --version 2>&1 | Out-File diag.txt -Encoding utf8
```

文件里没有版本号 → 子进程被吞 → 改用 Git Bash。

**结论**：idf.py / cmake / ninja / 编译器这类长任务一律走**Bash 工具（Git Bash）**；
PowerShell 工具只用于查询类 cmdlet，且结果要 `Out-File` 后再读。

## 二、PowerShell 把 stderr 包装成"红色报错"

`west build` / `cmake` 等把进度与警告打到 **stderr**，PowerShell 将其包装为
`RemoteException` / `NativeCommandError`（红色报错外观），但实际 `BUILD_EXIT=0`、产物正常生成。
属 stderr→error 误报，并非真失败。

- 判定真失败**以退出码为准**：脚本里 `echo %ERRORLEVEL%` / `exit /b %ERR%`，看 `BUILD_EXIT`。
- 脚本收尾不要留阻塞 `pause`（PowerShell 下会卡死或返回 255），用 `exit /b %ERR%` 便于拿到真实错误码。

## 三、长构建的正确执行方式

```bash
cd <proj> && ./build.sh > logs/buildN.log 2>&1; echo "EXIT=$?" >> logs/buildN.log
```

配 Bash 工具的 `run_in_background: true`，结束后再 grep 日志：

```bash
grep -n "EXIT=\|Project build complete\|FAILED\|error:\|warning:" logs/buildN.log
```

不要在前台硬等：会撞前台超时被自动 background，日志可能被截断。

PowerShell 侧要看输出则一律落文件再读：`... 2>&1 | Tee-Object -FilePath <build.log>`。

## 四、日志编码与"零警告"校验

PowerShell 重定向出的日志常是 **UTF-16LE**，按 UTF-8 读全是乱码或空：

```bash
python -c "d=open('build.log','rb').read().decode('utf-16','replace'); \
import re; print('\n'.join(l for l in d.splitlines() if re.search(r'warning|error|FAILED',l,re.I)) or 'NONE')"
```

## 五、产物时间戳：构建是否真跑了

**必须**对比源文件与可执行产物的 mtime：

```bash
ls -la --time-style=full-iso <build-dir>/<exe>
```

改了源码而 exe 时间戳没动 = 构建没真跑（增量构建静默跳过部分 target）。处理：加专门的重生成/
清理开关，或直接删除构建目录。

## 六、构建缓存不可信

`build/` 记录的是不存在的编译器路径（例如旧 MSYS2 工具链残留），或 `_deps` 里依赖源码没拉全
（FetchContent 中断）时，直接删掉重新生成到新的构建目录，**不复用陈旧缓存**。

另有一种 ACL 异常：在沙箱/提权模式下生成的 `build/`，其文件 ACL 可能只授予沙箱令牌写权限，
用户态重跑时 cmake Generate 阶段报：

```
ninja: error: failed recompaction: Permission denied
CMake Generate step failed.
```

此时文件看似 `rw-r--r--`、owner 正确、无 ReadOnly 属性、无残留进程，但就是写不进 `.ninja_log`。
修复：删除构建目录让用户侧脚本重新生成（构建产物可再生，删除安全）。stale-cache 检测通常只认
工具链字符串，不会清这类目录，需人工兜底。

## 七、`.bat` 的行尾与编码契约

编辑工具默认写 **LF 行尾 + UTF-8**，而 cmd.exe 解析 `.bat` **必须 CRLF + 纯 ASCII**：

- 纯 LF 会让 cmd 按空格/换行碎片化整文件执行，报一串 `'-xxx' 不是内部或外部命令` 之类
  token 碎片，`%%T` 退化成 `%T`。
- 注释里混中文（UTF-8 字节）在 GBK 控制台同样干扰解析。

改完必须复查：

```bash
tr -cd '\r' < x.bat | wc -c     # 应等于行数
grep -P '[^\x00-\x7F]' x.bat    # 应为空
```

另：`.bat` 里 `start "title" cmd /c "prog > log 2>&1"` 的内嵌引号会让 cmd 重定向解析失败
（日志文件不生成）。项目路径无空格时，`cmd /c` 内不加内层引号即可；外部工具走 PATH 裸名。

## 八、编码与断言

- `ipconfig` / `ping` / `netsh` 等输出是 **GBK**，解析前先转码：
  ```bash
  ping -n 3 -w 1500 -l $sz <IP> 2>&1 | iconv -f GBK -t UTF-8 | grep -c "字节=$sz"
  ```
- **不要用中文当 grep / 断言 pattern**：GBK 输出下会静默匹配失败形成假阴性（看起来"没连上"，
  其实已连上）。断言只用 ASCII（`TTL=`、`100%`、目标网段、HTTP 状态码）。
- Git Bash 会吞掉 `curl -w "%{http_code}"` 这类 `%{...}` 花括号（被当变量展开，输出形如
  `code=%http_coden`），导致判定全失败。改为按响应体特征判定：
  ```bash
  curl -s --max-time 5 http://<IP>/ | grep -q "<页面特征串>"
  ```

## 九、路径风格与可见性

- 原生 Windows 工具链看不到 MSYS 的 `/tmp`、`/dev/null`。探测文件（如宏体检用的 `probe.c`）
  放**工程目录内**，不放 `/tmp`。
- 传给原生 cmake 的路径必须 Windows 风格（`C:/...`），POSIX 风格（`/c/...`）无法解析。
- Git Bash 跑 exe 可能缺 DLL（如 GStreamer 的 `gio-2.0-0.dll`）：Bash 不继承系统 PATH，
  需显式前置依赖 bin 目录。

## 十、进程、端口与句柄排查

**Git Bash 的 `ps` 看不到 Windows 原生进程**，必须用：

```bash
tasklist | findstr <proc>
netstat -ano | findstr :<port>
taskkill /F /PID <pid>
```

两类高频现象：

- 烧录/调试偶发 `not found` / `init mode failed`，多因上一次 openocd / gdb 进程未退出仍独占
  调试器。查残留进程、结束后再重试；推荐常驻单个调试服务器，避免重复实例抢设备。
- 调试器报 `Target not examined yet` / `refuse gdb connection`，先查是否有两个 openocd 实例
  绑了同一组端口（如 3333/4444），只保留一个即可。
