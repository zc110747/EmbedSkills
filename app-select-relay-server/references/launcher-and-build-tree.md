# 一键构建 / 启动脚本：三个平台坑

配套 `app-select-relay-server/SKILL.md`。`.bat` 的解析规则、`set /a` 陷阱、沙箱跑批处理的
等效验证见 `win-batch-sandbox-probe` 与 `embedded-verification-acceptance/references/bat-script-rules.md`，
这里只写**本项目新增、且与"上位机服务"直接相关**的三条。

---

## 一、构建树**按平台分开**

Windows 与 WSL 常常**共享同一个工作树**，而 CMake cache 同时记录了**绝对路径**与**生成器**。
共用一个 `build/` 的后果：后跑的那个平台必然报**生成器不匹配**（而且是在配置阶段，看起来像
"CMake 坏了"）。

**约定**：

| 平台 | 构建树（Debug / Release） |
|---|---|
| Windows（`.bat`） | `build/`、`build-release/` |
| Linux / WSL（`.sh`） | `build-linux/`、`build-linux-release/` |

分开即彻底消除这个失效模式。**别忘了把四个目录都进 `.gitignore`。**

---

## 二、生成器复用策略：有 cache 就不要带 `-G`

```
目标目录已有 CMakeCache.txt ?
  ├─ 是 → 重新配置时【不带 -G、不带编译器参数】   （沿用 cache 里的生成器/编译器）
  └─ 否 → 优先 Ninja，否则 MinGW Makefiles
```

原因：对一个已有 cache 的目录传不同的 `-G` 会直接失败。**"复用"比"重新指定"更不容易坏。**

MSYS2 上还有个具体坑：它只提供 `make.exe`，**没有** `mingw32-make.exe` ⇒ 用
MinGW Makefiles 时必须显式给 `-DCMAKE_MAKE_PROGRAM=/path/to/make.exe`。

四条路径都要实测：**全新 Ninja / 复用 Ninja / 复用既有 MinGW / `--clean` 重建**。

---

## 三、参数校验：`set /a` 会把裸词**当成变量名**

```bat
REM 反例：--port abc 时
set "N=0"
set /a N=abc          REM abc 被解析为【变量名】；未定义即 0
if !N! LSS 0 ...      REM 两条范围检查全部通过
if !N! GTR 65535 ...  REM 垃圾值直接转给了服务
```

⇒ **非法端口被静默接受**。

**正解：回环校验** —— 数字重渲染必须逐字等于输入：

```bat
set /a N=!RAW! 2>nul
if not "!N!"=="!RAW!" (
  echo invalid value: !RAW!  (expected a decimal integer)
  call :pause_exit 1
)
```

副作用是顺带拒绝了前导零（`set /a` 会把 `01233` 按八进制读 —— 那本来就该拒）。

同样的处理要加给每一个数值参数（`--jobs`、`--max-clients`、`--poll-interval-ms`、…）。

> **验收要求**：每一条参数校验路径都要断言 **退出码 == 1 + 有解释文本 + 不打印成功横幅**。
> 只断言退出码不够 —— 曾经有一版在失败路径上仍打了成功横幅（见下）。

---

## 四、日志尾部输出：不要用 `more`

"构建失败时打印日志尾部"很容易写成 `for /f ... in ('more "tmp"')`。
**`more` 对文件会分页**并打印 `-- More --` 等按键 —— 在用户双击 `.bat` 的真实场景里，
它会吃掉后面的 `pause`。

**纯 cmd 的尾读写法**：

```bat
for /f %%c in ('find /c /v "" ^< "!LOG!"') do set "TOTAL=%%c"
set /a SKIP=TOTAL-25
if !SKIP! LSS 0 set "SKIP=0"
for /f "usebackq skip=!SKIP! delims=" %%l in ("!LOG!") do (
  set "LINE=%%l"
  echo !LINE!
)
```

- 用**延迟展开**输出：值不会再被当作命令重新解析（`&` `|` `(` `)` 安全）；
- **`skip=0` 这条路径必须有用例**：`set /a SKIP=TOTAL-25` 在日志很短时会得到负数，
  被 `LSS 0` 夹回 0 —— 曾经这里出过"短日志什么都不打"的回归。

---

## 五、启动脚本要**转发未知参数**

启动脚本只消费自己的开关（`--release --no-build --build-dir --no-pause -h`），
**其余一律原样转给服务**。否则服务文档化的开关（`--host --max-clients --console` …）
会被启动器**挡掉**，用户只会觉得"文档写了但用不了"。

少数需要**提前校验**的参数（`--port` / `--config` / `--stats`）额外做前置检查，
以便早报错、而不是让服务起来之后再退出。

---

## 六、其它两条环境注意

- **PATH 前置 `%SystemRoot%\System32`**：MSYS2 在 PATH 上的 `find.exe` / `sort.exe` 是
  GNU 版**同名异族**工具，会让 `find /c /v ""` 这类计数**静默给出错值**。
  （本项目历史上被 `sort -u` 坑过一次。）
- **`.bat` 契约**：CRLF + 纯 ASCII + 每条退出路径都 `pause`（`--no-pause` 供 CI）。
  这三条要能被验收脚本**静态查出来**（逐行 CRLF 精确计数、逐行 ASCII 扫描、
  结构断言 `call :pause_exit` **不带**返回码参数 —— 带了只会结束 `CALL`，
  调用方会掉进下一个标签，于是两个横幅都打印）。

> 行尾检查**只能用字节级计数**（`tr -cd '\r' | wc -c`、`od -c`、Python `data.count(b'\r\n')`）。
> 用 `grep -c $'\r'` 会两端都错：MSYS2 的 `grep` 以文本模式打开、**先剥 CR**（对真 CRLF 文件
> 恒返回 0 = 假阴性）；而 `$'\r'` 出现在命令替换里时还可能被解析成空串，
> 于是 `grep -c ""` 退化成"匹配全部行"（返回值恰等于行数 = 假阳性）。
