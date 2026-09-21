# 工具链安装、定位与版本锁定

## 一、通用工具（全部进系统 PATH，命令行可直接调用）

| 工具 | 用途 | 获取方式 |
|---|---|---|
| `arm-none-eabi-gcc` ≥13 | ARM 交叉编译器（15.3.1 实测可用） | ARM 官方 GNU toolchain releases |
| `cmake` ≥3.20 | 构建系统 | MSYS2：`pacman -S mingw-w64-ucrt-x86_64-cmake` |
| `ninja` | 构建后端 | MSYS2：`pacman -S mingw-w64-ucrt-x86_64-ninja` |
| `openocd` 0.12.0 | 烧录/调试 | SourceForge openocd 0.12.0-rc1 |
| `python` | 生成代码、跑验证脚本 | python.org |
| `gcc`（MSYS2 ucrt） | 编译 PC 侧测试桩 | `pacman -S mingw-w64-ucrt-x86_64-gcc` |

VSCode + Cortex-Debug 扩展一并安装，可 F5 一键编译调试。ST-Link / J-Link / USB 转串口
（CP210x 等）**驱动必须人工安装**，脚本与 Agent 装不了。

环境自检（任一 `command not found` → PATH 没配好，先解决再继续）：

```bash
arm-none-eabi-gcc --version
cmake --version
ninja --version
openocd --version
python --version
```

## 二、交叉工具链版本锁定：binutils 2.44 拒绝厂商预编译 `.a`

部分厂商预编译静态库（由 ARM Compiler/armcc 构建）在 **GNU ld 2.44**（随 arm-none-eabi-gcc
15.x 发布）下链接直接中止：

```
(.text.xxx+0x..): undefined reference to `GUI_xxx'
(GUI_xxx): Unknown destination type (ARM/Thumb)
dangerous relocation: unsupported relocation
```

**根因**：这类库目标文件缺 `.type %function` 与映射符号相关的严格性检查，binutils 2.44 收紧后
拒绝 interworking 重定位；给 `.a` 补 `$t` 映射符号无法绕过。

**已验证修复**：锁到 binutils < 2.44 的工具链（GNU Arm Embedded 13.3.rel1 / 14.2.rel1，
binutils 2.43.1），链接即正常。

锁定方式（杜绝 PATH 回退到 15.x）：在工具链探测模块里，把编译器/链接器/ar 等**以绝对路径
`FORCE` 写入 CMake 缓存**，并追加 `-B<tc_bin>` 让 gcc 驱动优先在该 `bin` 下解析 `ld`/`as`。

**经验规则**：凡用到厂商预编译 `.a`（GUI 栈、某些 DSP 库、闭源协议栈），先确认其 binutils
兼容性，必要时准备 binutils <2.44 的降级工具链，不要默认 newest。

## 三、Zephyr 工程的 west 调用

`west.exe` 不在 PATH 时不能直接 `west build`，必须走 python 模块：

```bash
python -m west build -b <board>/<soc> -d build -s .
```

每个新 shell 需注入（`GNUARMEMB_TOOLCHAIN_PATH` 用实际安装路径）：

```bash
export ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb
export GNUARMEMB_TOOLCHAIN_PATH=<arm-none-eabi 安装路径>
export PATH="$GNUARMEMB_TOOLCHAIN_PATH/bin:$PATH"
```

- `ZEPHYR_BASE` 优先取环境变量（west 自动注入），未设置时回退工程内 `zephyr/zephyr`。
- 在 MSYS2/Git Bash 里手动 export `ZEPHYR_BASE` 必须用 **Windows 风格绝对路径**（`C:/...`），
  用 POSIX 风格（`/c/...`）原生 cmake 无法解析。

## 四、ESP-IDF 环境定位

IDF 可能不在默认位置，先读安装器清单再 `ls` 确认：

```bash
cat "C:/Espressif/tools/eim_idf.json"   # 记录 path / python / activationScript
ls "C:/Espressif/tools/"                # cmake / ninja / xtensa-esp-elf / python 都在此
```

- IDF 根：`eim_idf.json` 的 `path` 字段（可指向自定义目录，**不要硬编码**）
- 工具链根：eim 默认 `C:\Espressif\tools`
- venv python：`<toolroot>\python\<ver>\venv\Scripts\python.exe`
- cmake：`<toolroot>/cmake/<ver>/bin`；ninja：`<toolroot>/ninja/<ver>`
- xtensa：`<toolroot>/xtensa-esp-elf/<ver>/xtensa-esp-elf/bin`

**MSYSTEM 早退**：idf.py 在 MSYS 下会因 `MSYSTEM` 环境变量报 "MSys/Mingw no longer supported"
后退出。二选一：

A. 用工程内环境包装脚本（推荐）：确认其中有 `unset MSYSTEM`，然后

```bash
source ./env.sh
"$PY" "$IDF_PATH/tools/idf.py" build
```

B. 自建 `idf.py` 包装器：

```python
import os, sys, runpy
os.environ.pop('MSYSTEM', None)
tools_dir = os.path.join(os.environ['IDF_PATH'], 'tools')
sys.path.insert(0, tools_dir)
sys.argv = ['idf.py'] + sys.argv[1:]
runpy.run_path(os.path.join(tools_dir, 'idf.py'), run_name='__main__')
```

## 五、MSVC x64 环境拼装（PowerShell）

**不使用** `-G "Visual Studio ..."`：MSBuild 在本机可能直接 ACCESS VIOLATION，产不出二进制。
一律 Ninja 驱动 cl.exe：

```powershell
cmake -S . -B build-msvc -G Ninja -DCMAKE_BUILD_TYPE=Release -D<PROJ>_BACKEND=gstreamer
cmake --build build-msvc
```

**不混用 MSYS2 的 cmake/ninja**：MSYS2 bash 会把冒号分隔的 PATH 透传给 cmd.exe，导致
rc.exe / mt.exe 找不到、链接失败。用 PowerShell 跑构建，保持分号分隔的原生 PATH 贯穿到链路末端。

手动拼环境（不依赖 vcvarsall，显式设 INCLUDE/LIB/PATH）：

```powershell
$Cl = Join-Path $Vc 'bin\Hostx64\x64\cl.exe'
$env:INCLUDE = "$Vc\include;$Kits\Include\$SdkVer\ucrt;$Kits\Include\$SdkVer\um;..."
$env:LIB     = "$Vc\lib\x64;$Kits\Lib\$SdkVer\ucrt\x64;$Kits\Lib\$SdkVer\um\x64"
$env:PATH    = "$Vc\bin\Hostx64\x64;$Kits\bin\$SdkVer\x64;$VsCMake\CMake\bin;$VsCMake\Ninja;$env:PATH"
```

- `$Kits = ${env:ProgramFiles(x86)}\Windows Kits\10`，`$SdkVer` 取 `Include/` 下最新 `10.0.x.x`
- VS 路径用 `vswhere.exe -latest -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath` 探测，探测失败再回退已知安装根
- VS 自带的 CMake/Ninja 在 `<VS 安装根>\Common7\IDE\CommonExtensions\Microsoft\CMake\{CMake\bin,Ninja}`
- 显式传 `-DCMAKE_CXX_COMPILER=<cl.exe 完整路径>`

等价路线：`call vcvarsall.bat x64` + 把 VS 自带 cmake/ninja 前置到 PATH，再 `cmake -G Ninja`。

## 六、GStreamer（MSVC）探测

"MSVC 需要 PKG_CONFIG_PATH" 是误导——MSVC 分支直接定位 devel 包，pkg-config 只服务 MinGW 分支。

```cmake
if(MSVC)
  find_path(_gst_inc  gst/gst.h    PATHS "${GSTREAMER_ROOT}/include/gstreamer-1.0" NO_DEFAULT_PATH)
  find_path(_glib_inc glib.h       PATHS "${GSTREAMER_ROOT}/include/glib-2.0"      NO_DEFAULT_PATH)
  find_path(_glibcfg  glibconfig.h PATHS "${GSTREAMER_ROOT}/lib/glib-2.0/include"  NO_DEFAULT_PATH)
  # 必需 .lib：gstreamer-1.0 gstapp-1.0 gstrtspserver-1.0 gstvideo-1.0 gstbase-1.0
  #          gobject-2.0 glib-2.0 gio-2.0（可选 intl ffi z），逐个 find_library NO_DEFAULT_PATH
else()
  find_package(PkgConfig)   # pkg_check_modules(GST gstreamer-1.0>=1.14 gstreamer-app-1.0 ...)
endif()
```

- 候选根顺序：`$ENV{GSTREAMER_ROOT}` → 官方默认安装目录；未设环境变量就逐个试，都没有才回退
- 必须安装 **MSVC 版 devel 包**；1.28 起 runtime/devel 合并为单个 exe，安装器加 `/TYPE=devel`
- 装到与 CMake 默认候选一致的目录可免传 `-DGSTREAMER_ROOT`
- 依赖的 element 由业务侧声明（采集源、videoconvert、编码、parser、payloader、sink）

## 七、可选依赖与开关宏

```cmake
include(FetchContent)
FetchContent_Declare(spdlog GIT_REPOSITORY https://github.com/gabime/spdlog.git
                     GIT_TAG v1.14.1 GIT_SHALLOW ON)
FetchContent_MakeAvailable(spdlog)      # 业务只 target_link_libraries(x PRIVATE spdlog::spdlog)
```

需 GitHub 可达（`git ls-remote` 可先行验证）。多后端工程的开关范式：

```cmake
option(<PROJ>_BUILD_TESTS "Build the test suite" ON)
set(<PROJ>_BACKEND "auto" CACHE STRING "gstreamer|sim|auto")
add_compile_definitions(<PROJ>_VERSION="0.1.0")
# 每个后端分支额外定义 <PROJ>_BACKEND_<NAME> 与 <PROJ>_BACKEND_NAME="<name>"
```

源码侧用 `#ifndef <PROJ>_BACKEND_NAME` 兜底为 `"unknown"` 并打印后端名。
