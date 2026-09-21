# CMake / Ninja 交叉编译与工程骨架细节

主副本对应 SKILL.md「核心知识点」中的目录分层、设备层、HAL 按需引入、构建要点。本文只讲 GCC/CMake 侧配方。

## 一、目录分层（完整形态）

```
<project>/
├── app/            应用逻辑（main.c、业务模块、RTOS/LwIP 移植、shell、app_ui.c）
├── bsp/            用户开发的板级驱动（bsp_uart / bsp_led / bsp_i2c / bsp_sdram ...）
├── Drivers/        CMSIS-Core / CMSIS-Include / DSP / NN 与 ST 官方 HAL（不手改）
│                   禁止放 CMSIS-Device(ST)
├── sys_startup/    本地设备层：device 头 + system_<系列>xx.c
│                   + startup(gcc/arm/iar) + 本工程链接脚本 *.ld
├── third_party/    第三方库（TinyUSB / LVGL / FatFs / LwIP / FreeRTOS / mbedTLS）
├── cmake/          交叉工具链文件 arm-none-eabi.cmake
├── <工程>.cfg      OpenOCD 烧录/调试配置，放工程根（与 .vscode 同级）
├── <芯片>.svd      MCU SVD 寄存器描述，放工程根，供 cortex-debug 加载
├── tools/          PC 端工具与 verify 脚本（python / C#）
├── .vscode/        c_cpp_properties.json / launch.json / tasks.json / settings.json
├── CMakeLists.txt
└── CMakePresets.json
```

铁律：
- HAL 驱动只放 `Drivers/`，用户驱动放 `bsp/`，第三方库放 `third_party/`，统一管理便于复用。
- 设备层（startup 向量表 / `system_*.c` / device 头 / 链接脚本）一律放工程本地 `sys_startup/`，
  禁止依赖 `Drivers/CMSIS/Device/ST/...` 那棵官方树。
- 构建/调试产物一律相对路径，不写死本机绝对路径。
- `*.svd` / `*.cfg` 放工程根，不需要 `openocd/` 子目录。
- `third_party` 体积大，宜把可复用的 `Drivers/` / `third_party/` 打包随工程分发，解压即用
  （解压脚本对已存在条目跳过，不覆盖）。

## 二、源集切分

- **`add_executable` 的 startup / `system_*.c` 必须显式列出**，禁止 `GLOB_RECURSE` 整树收集：
  CMSIS-Device 树含数十个型号 × gcc/arm/iar 三套语法的 startup，全收会重复定义
  `Reset_Handler` / `SystemInit`，且把 iar/arm 语法 `.s` 喂给 GCC 汇编器直接语法错。
- **新增 `.c` 源文件必须重跑 `cmake` 重新 GLOB**：`file(GLOB ...)` 在配置期展开并缓存，
  Ninja 增量不会自动重扫，否则新文件不进编译。
- 链接脚本改动必须让 CMake 跟踪（`LINK_DEPENDS` 指向 `*.ld`），否则改 `.ld` 不触发重链。
- 工具链文件（`cmake/arm-none-eabi.cmake`）集中放 `CMAKE_C_FLAGS` / `MCU_FLAGS`
  （`-mcpu` / `-mthumb` / `-mfpu` / `-mfloat-abi`）与链接选项，各工程复用同一份。

## 三、HAL 按需引入（GCC 侧）

**禁止 `GLOB` 整目录收集 HAL**。按代码里实际用到的符号反查模块：

```bash
# 反查：源码里用到哪些 HAL_XXX_ 模块
grep -rhoE "HAL_[A-Z0-9]+_" app bsp Core --include=*.c --include=*.h | sort -u
# 清点 HAL 源目录（不要整包收）
ls Drivers/STM32<系列>xx_HAL_Driver/Src
```

规则：
- 任何工程都含基础件：`hal.c` / `hal_cortex.c` / `hal_rcc.c` / `hal_rcc_ex.c`，再加 `hal_gpio.c`。
- H7 系列必须连 `_ex.c` 一起带的模块：RCC / FLASH / DMA / TIM / PWR。
- `hal_msp.c` 与 `hal_it.c`（中断服务）属用户 `Core/Src`，不属 HAL 源集。
- 引入**新外设**时，必须把对应 `hal_<模块>.c`（及 `_ex.c`）同时补进 **CMake 源集**与
  **MDK-ARM uvprojx 的 HAL 组**，否则链接报 `undefined reference to HAL_XXX_Init`。

验收红线：HAL 入组 `.c` 数量应为**个位数~十几个**（按实际外设），不是目录全量
（H7 约 80+）；且 uvprojx 中 HAL 组文件数应等于 CMake 侧 HAL 源列表条数。

## 四、链接脚本

- 栈顶符号 `_estack` 与 RAM 段 `LENGTH` 必须按芯片**真实容量**填写，写大即静默越界。
- 外部内存段（SDRAM / PSRAM / QSPI 映射区）必须标 `(NOLOAD)`，否则初始化代码会试图搬数据。
- `.ld` 与分散加载文件是同一份内存布局的两种表达，改一边必须同步另一边。
- 帧缓冲一类 DMA 目标段要显式落到 DMA 可达域（H7 DCMI 仅可达 AXI SRAM，DTCM 不可达）。

## 五、CMakePresets

提供 `debug` / `release` 预设省去重复 `-D`：

```json
{ "configurePresets": [
  {"name":"debug",   "cacheVariables":{"CMAKE_BUILD_TYPE":"Debug"}},
  {"name":"release", "cacheVariables":{"CMAKE_BUILD_TYPE":"Release"}}
] }
```

构建：`cmake --preset debug && cmake --build build/debug`。

预设工程的 build 子目录必须与 `binaryDir` 一致，否则 `tasks.json` 的 `build`/`flash`
路径对不上。按工程需要可再加变体预设（如切换 USB 速率、HSE 频率）。

## 六、VSCode Cortex-Debug（裸工具名 + 根级 cfg/svd）

工具链在系统 PATH 时，所有引用只写裸程序名（不加安装目录、不带 `.exe`）：

- `launch.json`：`"openocdPath": "openocd"`、`"gdbPath": "arm-none-eabi-gdb"`
- `settings.json`：`"cortex-debug.openocdPath"` / `"cortex-debug.gdbPath"` 同上，
  `"C_Cpp.default.compilerPath": "arm-none-eabi-gcc"`
- `configFiles` / `svdFile` 用 `${workspaceFolder}` 指向工程根的 `*.cfg` / `*.svd`

```json
{
  "executable": "${workspaceFolder}/build/debug/<target>.elf",
  "configFiles": ["${workspaceFolder}/<工程>.cfg"],
  "openocdPath": "openocd",
  "gdbPath": "arm-none-eabi-gdb",
  "device": "STM32<型号>",
  "interface": "swd",
  "rtos": "auto",
  "svdFile": "${workspaceFolder}/<芯片>.svd",
  "preLaunchTask": "build"
}
```

- `rtos` 字段按实际内核填写（Zephyr 工程填 `"Zephyr"`，裸机/FreeRTOS 用 `"auto"`）。
- `preLaunchTask: "build"` 让 F5 先编译再调试。
- 严禁写死 `<openocd 安装目录>/bin/openocd.exe`、`${env:...}/...` 等本机或环境变量路径。

多工程批量统一：`tasks.json` 只保留 `configure` / `build` / `clean` / `flash` 四个任务，
构建机制按工程现状保留（不强行统一为 CMake）；批量检索工程时排除 `.gitignore` 中的目录。

## 七、多工程一键脚本族（编排层）

分工固定为三层：

| 脚本 | 位置 | 职责 |
|---|---|---|
| 工程构建脚本 | 每个工程根 | 检查工具与依赖 → `configure → clean → build`，失败即中止，所有出口 `pause` + `exit /b %ERR%` |
| 汇总脚本 | 各工程上一层仓库根 | `call` 各工程脚本顺序编译；出错才 `pause` 继续；末尾汇总 `Passed/Failed/Skipped` |
| 支持包脚本 | 仓库根 | 按工程类型把支持包目录（`Drivers`/`third_party`/…）解压到各工程并补齐缺失条目（已存在打 `[SKIP]`，不覆盖） |

脚本编写注意（不要凭记忆手写）：
- `.bat` 一律**纯 ASCII + CRLF**；`echo` / `REM` 文本里的 `& ( ) | < >` 必须清洗——
  这是 `.bat` 报「此时不应有 .」类错误的**第一嫌疑**。
- `cd /d "%~dp0"` 的尾随反斜杠问题：正确写法是先去尾部 `\` 再 `cd`。
- `for` 循环块内**不能用 `goto`**（会中断整循环），改 `call :子例程`；块内 `2>&1` 写 `2>nul`。

> `.bat` 的通用坑清单在外层 skill `embedded-verification-acceptance/references/bat-script-rules.md`，
> 本文只讲 ST 工程脚本特有的部分。

## 八、startup 向量表（FreeRTOS 工程）

用 FreeRTOS V11 时，startup 的 SVC/PendSV/SysTick 必须**直指** port 函数（不做转发包装）：

```asm
.word vPortSVCHandler      /* SVCall */
.word xPortPendSVHandler   /* PendSV */
.word xPortSysTickHandler  /* SysTick */
```

FreeRTOS 独占 SysTick 会导致裸机 HAL 时基（`HAL_Delay`）冻结，需在 `HAL_InitTick` 之外
另行提供时基（常见做法：HAL timebase 改到某通用定时器）。
