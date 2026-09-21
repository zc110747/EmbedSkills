# 故障定位决策树、环境陷阱与端到端验收清单

场景：**东西编出来了但跑不起来**，如何在最短时间内定位到"到底是哪一环"。

## 一、故障定位决策树（按序排查，别跳步）

```
现象：整条链路不工作
  │
  ├─ 0. 二进制是不是旧的？  比对 exe mtime 与最新源码 mtime
  │      报错文案在当前源码里 grep 不到 → 百分百是跑了旧二进制（改了源码没重新构建）。
  │      这是"预检全绿但启动就挂"的头号原因：修好的逻辑在源码里，跑的却是上一版 exe。
  │      根治：一键启动脚本里加源码/二进制 mtime 比较，过期就自动重建。
  │
  ├─ 0b. 构建脚本一上来就挂在 configure？  看 configure 日志有没有
  │      "is different than the directory" / "does not match the source"
  │      → 工程文件夹被改名或移动过，CMake 缓存里的绝对路径指纹失效，见 §三·E。
  │      不要改 CMakeLists、不要怀疑工具链，删 build/ 重配即可。
  │
  ├─ 1. 进程还在不在？  tasklist | grep -iE "<链路所有 exe>"
  │      有残留 → taskkill /F /IM 全清，再重跑（最常见）
  │
  ├─ 2. 脚本输出说什么？  读启动脚本落的输出/日志文件
  │      预检 [FAIL] → 工具/exe 没找到，补 PATH 或重建
  │      [AUTO] 回退提示 → 设备索引不对，已自动修正或未找到设备
  │
  ├─ 3. 采集端自己起没起？  读 agent 日志
  │      "Failed to start" / "Failed to set pipeline to PLAYING"
  │        → 设备索引错 / 设备被占 / caps 协商失败（见 §四）
  │      STREAMING + frames 递增 → 采集端正常，问题在下游
  │
  ├─ 4. 服务端收到没有？  读 server 日志
  │      "is publishing to path '<id>'" → 发布成功
  │      "is reading from path '<id>', with TCP, 1 track (H264)" → 拉流成功
  │      "no stream is available on path" → 上游没推上来，回到第 3 步
  │
  └─ 5. 播放端？  窗口不出现 → 参数非法（见 §五）
```

**日志可信度排序**：逐行实时刷盘的服务日志（最可信）> 采集端 stdout（有缓冲，可能陈旧）> 脚本控制台输出（最不可信，常被环境吞掉）。
判定"自动恢复"这类时序敏感结论，**必须**以最可信那份为准。

## 二、环境与路径陷阱

### 2.1 命令名解析被遮蔽：先确认"实际跑的是哪个程序"

Bash 工具里"脚本什么都没输出"**不等于**脚本有错 —— 先怀疑**命令名被 PATH 遮蔽**，而且**报错会被吞**。

| 敲的 | 实际跑到的 | 症状 | 怎么办 |
|---|---|---|---|
| `bash x.sh` | `which -a bash` 首项是 `System32\bash.exe`（WSL 启动器） | 沙箱拦 `wsl.exe`；**stdout 被整段丢弃** ⇒ 看起来像"脚本一行都没跑" | 用 `/usr/bin/bash x.sh`（或 `sh x.sh`）。shebang 写 `#!/usr/bin/env bash` 会踩同一个坑 ⇒ 写 `#!/usr/bin/bash` |
| `./node_modules/.bin/<tool>` | npm 生成的 shim 先 `cygpath -w` 再 exec（反斜杠路径走歪） | 同左被拦 | 直接 `node node_modules/<pkg>/bin/<tool>.js …` |
| `sort -u` | `System32\sort.exe`（不认 `-u`） | **静默返回空**（"按 PID 清理进程"的循环一个都没杀 ⇒ 误判清理成功） | `awk '!seen[$0]++'` 或 `/usr/bin/sort` |
| `timeout 12 <cmd>` | `System32\TIMEOUT.EXE` | 报"无效语法。默认选项不允许超过 '1' 次" | 超时保护改用后台任务 + 按端口取 PID + `taskkill -F -PID` |
| `find . -name` | `System32\FIND.exe` | `参数格式不正确` | 用 Bash 内置逻辑或专用搜索工具 |
| `taskkill //PID`（双斜杠） | MSYS 路径转换 | 静默失败，进程没杀掉 → 旧进程继续占端口 / 设备（曾伪装成"新服务 bind 失败"） | `MSYS2_ARG_CONV_EXCL="*" taskkill /F /IM <exe>.exe`；按端口反查 PID 用 `netstat -ano \| grep :<port>` |
| `grep "\b…"`（漏 `-E`） | GNU grep | `\b` 紧贴 `)` 时退化成字面量 ⇒ 端口预检**恒返回"干净"** | 用 `-E` / 简化模式 |

**通用诊断法**：`which -a <cmd>` 看首项；`od -c` 看输出文件**真实字节**（若只有几字节 `?????`，不必继续猜）。
⚠️ **判工具身份不要匹配路径字符串**：同一份二进制可能同时以 `/tmp/system32/...` 与 `/c/Windows/system32/...` 出现（沙箱注入的硬链接镜像），按路径写的预检**会假通过**。要按**行为**判（如 `timeout 1 true` 是否报 Windows 版语法错误），或只匹配目录族。

**心智模型**：命令行工具的"参数语义"没验证过，就等于没有这个工具。

### 2.2 `/x/...` 与原生路径分两种待遇

- bash **自己的重定向 / 管道**认 `/d/...`：`cmd > /d/x.log` 正常。
- 作为**参数交给原生 Windows 程序**（git / python / node / curl / gcc / 工具链）时**不认**，必须写 `D:/...`：
  - `git apply /d/x.patch` → `can't open patch`（文件明明存在）；
  - `python x.py --image-out /d/f.jpg` → `FileNotFoundError`；
  - `curl -o /d/f.html` → **exit 23 写错误，但 `status` 仍是 200** —— 最容易误判成"服务坏了"。
- **更隐蔽的一种**：给原生 exe 传 MSYS2 路径时它按字面量解析 → 报「文件不存在」→ **静默 fallback 到内置默认值**，于是验证的根本不是预期的那份配置（程序不报错，只是"用错配置跑对了"）。
- **判据**：报错说"文件不存在 / 写不进去"而 `ls` 明明能看到 → 先想这条，别去查业务逻辑。凡 `-o` / `--out` / `-I` / `--config` 这类输入输出路径参数都一样。
- Git Bash 的 `/tmp` 对 MSYS2 工具链**不可见**（两者 `/tmp` 不是同一路径）：临时源文件写成工程目录下的相对路径再编译，编完删掉。
- 终端把 UTF-8 中文显示成乱码时，先用 `od -c` 看**真实字节**再判断是不是编码 bug。

### 2.3 长驻进程 / 跨调用被回收（最有欺骗性的一类）

- 上次调用 `start` 起的服务，下次调用时已死；`(cmd &)` / `nohup cmd &` 都救不了。
- **实证症状**：`curl` 第一次 200、第二次 `HTTP 000`（连接被拒），且服务日志**没有**任何退出打印（被 SIGKILL 而非优雅退出）。
- **唯一可靠办法**：用 Bash 工具的 `run_in_background=true` 起进程（跨调用存活），配合服务自身的 shutdown 接口收尾。判据：`tasklist | grep <exe>` 为空 = 已被回收。
- **一键脚本场景最欺骗性的一种**：启动脚本本身 **exit 0**（它打印的"accepting connections"是真话），但**下一次调用**里 `netstat` 已无该端口、相关进程一个不剩，连 `start` 开出的新控制台窗口也一起被收。
  ⇒ **launcher 的退出码不能用来推断"服务还活着"**。验证一键脚本必须写成**一次调用内**：

  ```bash
  ./x.bat < /dev/null; echo "exit=$?"; netstat -ano | grep :<port>; curl ...
  ```

  分两次调用就永远看不到服务的后半段。

### 2.4 沙箱 / Agent 环境跑 exe 的坑

| 限制 | 表现 | 绕法 |
|---|---|---|
| 二进制前台运行被拦（`start cmd /c` 也拦） | 无法前台跑长驻 exe | Bash 工具 `run_in_background=true` |
| 禁止 `[Diagnostics.Process]::Start` / `Add-Type` | `equivalent to Start-Process` / `Add-Type compiles and loads .NET code` | 造 mock / 辅助 exe 用 gcc 编译真 `.exe` |
| 拿不到真实退出码 | 工具报的 exit code 与脚本实际返回值常相反 | 写 wrapper `.bat`：`call 目标.bat %*` 后 `echo EXITCODE=%errorlevel%`，从输出里 grep；或 Bash 工具 `${PIPESTATUS[0]}` |
| 派生的 cmd 子进程 **PATH 被剥空** | `.bat` 里 `where <tool>` 报 9009「不是内部或外部命令」，而 System32 存在、CWD 正确 | 脚本内**不要**替环境打补丁。**凡依赖 PATH 的 `.bat`，功能验证只能在 Bash 工具里做** |
| `Start-Process -RedirectStandardOutput` | 目标 `.bat` **完全不执行**，ExitCode 为空、文件 0 字节 | 要输出就用 Bash 工具捕获；PowerShell 侧只用退出码 + 进程副作用判定 |
| Bash 工具调 `powershell.exe` | `Command blocked: Invoking PowerShell from Bash bypasses PowerShell security checks` | 无绕法 |
| 沙箱内包管理器 / 构建工具失败（如 NuGet 路径为 null、`reg.exe` 被黑名单拦） | 栈顶 `Path.Combine(null, …)`；`vcvarsall.bat` 同样调 `reg.exe` | 属环境问题，手动赋回环境变量也无效；用 mock 工具链或跳过该步骤只验脚本骨架。被黑名单拒绝的（如 `wmic.exe`）**不要绕道重试** |
| 跨调用进程回收 | 见 §2.3 | `run_in_background`，且验证写在同一调用内 |
| 沙箱拦**产物目录写入** | 链接期 `cannot open output file <产物>: Permission denied`，stderr 同时列 `(读/写 · 拒绝)`，甚至有 `[sandbox] 命令被沙箱拦截` 块 | 这是沙箱拦截，不是代码 / 权限错误。构建与测试一律用 Bash 工具 + 关闭沙箱 |
| Git Bash 不继承 GUI 工具链的 PATH | 直接跑 exe 报某 `*.dll` 缺失 | 先 `export PATH="/c/Program Files/<SDK>/bin:$PATH"` |
| 终端编码 | 中文乱码被误判为编码 bug | 见 §2.2 |

### 2.5 「产物写不进」的三种成因（先分清再动手）

| 症状 | 成因 | 处置 |
|---|---|---|
| `cannot open output file <产物>: Permission denied` + **有**沙箱拦截块 | 沙箱禁止写该目录 | Bash 工具 + 关闭沙箱 |
| 同样报错但**没有**沙箱块，且关掉沙箱**仍复现** | **目标进程还在运行，持有 exe 文件锁**（Windows 不允许写正在执行的 PE） | 先杀进程再链接 |
| `undefined reference to <符号>` | 源清单缺文件（真实代码问题） | 补 CMake 源清单 |

前两种**症状字面完全相同**，唯一可靠区分方式是**看有没有 `[sandbox] 命令被沙箱拦截` 块**。
「已经关沙箱还报 Permission denied」= 立刻去查进程，不要再怀疑权限或代码：

```powershell
Get-Process -Name <app名> -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force }
```

⚠️ 桌面 GUI 程序尤其易踩：用户开着界面看效果，agent 这边就永远链接不上。**改完代码要构建前先确认 app 没在运行。**
⚠️ 三种成因可能**同时出现在同一份构建输出里**（先因沙箱丢掉若干目标，再暴露一个真实链接错误）—— **逐条读 FAILED 块**，把 `undefined reference` 和 `Permission denied` 分开处理。

### 2.6 让长驻 GUI / 服务可被反复验证（不干扰用户实例）

用**「全部状态外置」**：把配置、静态资源、数据目录都指向临时目录，端口也换掉。

```bash
./app.exe --config X:/tmp_verify/config.json \
          --web    X:/tmp_verify/web \
          --data   X:/tmp_verify/data \
          --port   <port>
```

- 路径必须是**原生形式**（见 §2.2），否则静默回退到内置默认值。
- 端口优先用命令行开关覆盖，**先确认该开关真的接上了**（搜代码里有无该选项），否则同样静默走配置里的旧端口。
- 要端到端验证又不想碰用户的在用实例，这是唯一省事的办法。

## 三、构建与缓存

### A. 构建目录清理（sandbox safe-delete 拦截坑）

CI / 沙箱里 `rm -rf build` 可能触发 **safe-delete 批量确认拦截**（文件数超阈值时命令被拦、实际未执行），导致陈旧 `build/` 被复用、新增源文件没进编译，出现"改了代码却没生效"的假象。

- 用 `cmake --fresh -B build` 强制重配（最稳，保留目录名），或改用全新目录名（`build_dbg` / `build_rel`）。
- ⚠️ 只要动过 `CMakeLists.txt` 的 `GLOB` 源清单（新增源文件），**必须重跑 cmake 重新 GLOB**，ninja 增量不会自动重扫。

### B. 项目目录改名 / 移动后 CMake 缓存失效（configure 直接失败）

```
CMake Error: The current CMakeCache.txt directory <新路径>/build/CMakeCache.txt is different
            than the directory <旧路径>/build where CMakeCache.txt was created.
CMake Error: The source "<新路径>/CMakeLists.txt" does not match the source "<旧路径>/CMakeLists.txt"
            used to generate cache.
```

- **根因**：`build/CMakeCache.txt` 里有两行**绝对路径指纹**（`CMAKE_HOME_DIRECTORY:INTERNAL` / `CMAKE_CACHEFILE_DIR:INTERNAL`），工程一改名 / 移动就与新路径不符，CMake 出于"防产物写错地方"直接拒绝 configure。
- **一次性处置**：删掉整个 `build/`（或至少 `CMakeCache.txt` + `CMakeFiles/`）再 configure。
- **根治——写进一键构建脚本**：configure 前读缓存里的源码路径，不符就自己重建。

  ```bat
  :heal_stale_cache
  if not exist "%BUILD_DIR%\CMakeCache.txt" exit /b 0
  set "_cached_src="
  for /f "usebackq tokens=1,* delims==" %%A in ("%BUILD_DIR%\CMakeCache.txt") do (
      if /I "%%A"=="CMAKE_HOME_DIRECTORY:INTERNAL" set "_cached_src=%%B"
  )
  if not defined _cached_src exit /b 0
  set "_cached_norm=%_cached_src:/=\%"          REM 缓存存 / 分隔，必须归一化再比
  if /I "%_cached_norm%"=="%PROJECT_DIR%" exit /b 0
  echo [WARN] stale cache for %_cached_src% - rebuilding the tree
  call :wipe_build
  exit /b 0
  ```

  三个必踩细节：**斜杠方向**必须归一化（否则永远不相等 → 每次构建都白清一次）；**枚举逻辑放 `:子程序`**（含引号的复合命令嵌进 `if (...)` 深块会被解析期拆坏）；**擦除逻辑要能一眼看穿**。
- **别在擦除时挑着保留，要把交付物搬到 `build/` 之外**：擦除逻辑一旦要枚举"该删什么 / 该留什么"，多一个子目录就漏一个，还容易与 configure 的清理需求打架。承认 **`build/` 整个可抛弃**，需要跨 clean 存活的东西在构建成功后 copy 到 `build/` 之外。
- **用户长期维护的交付目录（放运行时依赖：DLL 闭包 / TLS 信任库 / 配置 UI / 数据文件）脚本只能"刷新产物"，绝不能删** —— 否则等于把用户的运行时依赖删掉，用户立刻发现"软件不能工作了"。
- **兜底**：预检之外再包一层「configure 失败 → 在日志里匹配 `different than the directory` / `does not match the source` → 清一次重试」。判据必须**同时**匹配那两句原文，否则会把真实编译错误当成缓存问题无限重试。
- **心智模型**：凡把「绝对路径」写进持久化状态的工具（CMake 缓存、增量编译中间目录、IDE 的 `.vs/`、包管理器的 lock 与 node_modules），工程一搬家就失效——脚本要么自愈，要么把这类路径全部参数化。

## 四、自动协商与 caps 失败（采集类链路高频）

- `videoconvert` **只转像素格式，不做缩放**。所以强制 `width`/`height` caps 而设备产不出该规格 → 链接 / 协商失败 → 进重连死循环。
- 想让客户端拿到固定尺寸而设备原生是别的尺寸，**必须加 `videoscale`**，否则必然失败。
- 协商上报要查**采集源 pad 的 src**（那里才是设备原生格式且一定有固定 caps）；查编码器 sink pad 常只拿到模板 caps（无 width/height）→ 解析静默失败、日志里什么都没有。
- 协商结果**只在值变化时打印**；`start()` 与 `STATE_CHANGED` 两处都触发会导致同毫秒打两行。
- 低延迟参数组（已验证可用）：

  ```
  ffplay -rtsp_transport tcp -fflags nobuffer -flags low_delay \
         -probesize 32768 -analyzeduration 0 -framedrop \
         rtsp://<host>:<port>/<path>
  ```

  ⚠️ **不要加 `-rtsp_flags nobuffer`**：`rtsp_flags` 不接受该值，ffplay 直接 `Invalid argument` 退出、**窗口永远不出现**（`nobuffer` 属于 `-fflags`）。这是"ffplay 打不开"的头号原因。
- 服务端配置关键项：允许推任意路径（否则报 `path '<id>' is not configured`）；传输方式与推流端一致（避免 UDP 乱序）；不落盘（不引入额外缓冲）。

## 五、端到端验收清单

| 阶段 | 检查项 | 通过标准 |
|------|--------|----------|
| 单测 | 测试运行器 + `--output-on-failure` | 全部 pass |
| 构建 | 编译输出 | **0 warning / 0 error** |
| 预检 | 启动脚本工具探测 | 全部 `[OK]`，无 `[FAIL]` |
| 采集 | 采集端日志 | STREAMING + frames 递增 + dropped=0 |
| 协商 | 采集端日志 | 打印实际协商出的格式 `WxH @ Ffps` |
| 服务端 | 服务日志 | `is publishing to path '<id>'` |
| 拉流 | 服务日志 | `is reading from path '<id>', with TCP, N tracks (...)` |
| 断线 | 杀掉服务 | 采集端**不退出**，按指数退避重试 |
| 恢复 | 重启服务 | 自动恢复 STREAMING（**以最可信日志判定**） |
| 守卫 | 新写的回归测试 | **在旧代码上真的失败过**。⚠️ 若该测试 `import` 了新符号，拿旧代码跑只会收集期 `ImportError` —— 那证明的是"符号是新的"，**不是"旧行为是错的"**。补一个**只用旧行为**的探针（把旧常量写死在自己源码里）跑一次，看它打出缺陷本身 |
| 文档 | 写进文档的每个数字 | **重复测到稳定再写**（实测同一脚本，参数差一个就是另一个数） |
| 依赖清单 | 仓库里有没有 requirements 清单、脚本是否用 `-r` 引用 | 清单散落在脚本字符串里 = **没有出处**；`.bat` 解析不了 requirement 行 ⇒ 必须有一条静态测试钉住 |
| 一键脚本的自举 | 改完这类脚本，**两条路径都要真跑** | stdin 关闭（`< /dev/null`）⇒ 走**拒绝**且**没建目录**；管道送 `Y` ⇒ 建好、装好、继续启动。只跑一条等于没验 |

> 延迟评估：先测**内部**延时（正常应在 ~20ms 量级）。若用户报总延迟 >1s 而内部只有 20ms，瓶颈在服务端 / 播放端 / 网络，或**采集源原生帧率本身的固有间隔**（如 8fps = 125ms/帧），不要再去内部找。
