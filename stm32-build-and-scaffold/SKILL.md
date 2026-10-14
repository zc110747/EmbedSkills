---
name: stm32-build-and-scaffold
description: STM32 工程的统一骨架与构建规范：CMake+Ninja 交叉编译、HAL 按需引入、Keil MDK 移植与 UV4 命令行构建、OpenOCD 烧录、用 Keil 产物接 VSCode Cortex-Debug 调试。适用于"新建 STM32 工程""搭 CMake 构建""移植到 Keil""链接报未定义 HAL 符号""Keil 下 HardFault / 栈太小"等请求。
agent_created: true
---

# STM32 工程骨架与构建

一套目录分层 + 两套构建后端（CMake/Ninja + arm-none-eabi-gcc、Keil MDK-ARM）。配套 `embedded-windows-toolchain`、`embedded-verification-acceptance`。

## 何时用

- 新建或整理工程骨架、CMake 构建、Presets、Cortex-Debug。
- 移植到 Keil MDK-ARM（uvprojx + 分散加载）或用 UV4 构建。
- 用 Keil 构建产物接 VSCode Cortex-Debug 调试（`.axf` 只取符号，不 `load`）。
- 编译慢、Flash 虚高、链接报未定义 `HAL_XXX_Init`；**GCC 构建正常而 Keil 构建进 `HardFault`**。

## 核心知识点

**目录分层**：`app/`（应用）· `bsp/`（板级驱动）· `Drivers/`（ST 官方 HAL/CMSIS，不手改）· `sys_startup/`（本地设备层）· `third_party/` · `cmake/` · `tools/`。驱动按归属放对应目录，不混放。

**设备层必须本地化**：startup 向量表、`system_<系列>xx.c`、device 头、`*.ld` 一律放工程内 `sys_startup/`，不依赖 `Drivers/CMSIS/Device/...` 官方树——整树收集会重复定义 `Reset_Handler`/`SystemInit`，并把 iar/arm 语法喂给 GCC。

**HAL 按需引入**：禁止 `GLOB` 整目录收集 HAL 驱动，按代码里的 `HAL_XXX_` 反查模块只列所需 `.c`。任何工程都含 `hal.c`/`hal_cortex.c`/`hal_rcc.c`/`hal_rcc_ex.c`（+ `hal_gpio.c`）；H7 的 RCC/FLASH/DMA/TIM/PWR 须连 `_ex.c` 一起带。**新增外设时 CMake 源集与 uvprojx 的 HAL 组同步补齐**，否则链接未定义。

**CMake**：`add_executable` 的 startup / `system_*.c` 显式列出，不用 `GLOB_RECURSE` 整树收集；`file(GLOB ...)` 在配置期展开并缓存，**新增 `.c` 必须重跑 `cmake`**（Ninja 增量不会重扫）；改 `.ld` 靠 `LINK_DEPENDS` 才触发重链。栈顶 `_estack` 与 `RAM LENGTH` 按芯片真实容量，外部内存段必须 `(NOLOAD)`。

**工具写裸名、路径写相对**：`openocd` / `arm-none-eabi-gdb` / `arm-none-eabi-gcc` 走 PATH；`configFiles`/`svdFile` 用 `${workspaceFolder}` 指向工程根；不写安装目录、环境变量路径、绝对路径（换机器即失效）。`*.svd` 与 `openocd.cfg` 放工程根（与 `.vscode` 同级）。

**FreeRTOS**：startup 的 SVC/PendSV/SysTick 向量**直指** `vPortSVCHandler`/`xPortPendSVHandler`/`xPortSysTickHandler`；SysTick 被独占会冻结裸机 `HAL_Delay` 时基，需另配时基（如 HAL timebase 改到定时器）。

**OpenOCD**：0.12 用 `transport select swd`，不支持旧 `hla_swd`；H7 用 `stm32h7x.cfg`、F4 用 `stm32f4x.cfg`。`[find ...]` 脚本缺失/路径错属配置错误；"no probe attached" 类 adapter 报错属正常（需真机）。

**Keil 侧的反向约定**：`syscalls.c`（GCC/newlib 垫片）**必须排除**；半主机抑制垫片（`__use_no_semihosting` + `_sys_exit`/`_ttywrch`）**必须保留**——两者方向相反，极易搞错。`uThumb=1`/`thumb=1` 必开（Cortex-M 只认 Thumb）。ARMCLANG 警告参数用**单横杠** `-Wno-...`。Keil 全量入组会真的链进代码（无 `--gc-sections` 兜底）。

**两个易漏的"另一份数据"**：① 第三方库**头文件**里的 newlib 专有宏（`_ansi.h` / `_BEGIN_STD_C`）**不是可排除项** —— 就地展开成 `extern "C"` 守卫，改完**必须回归 GCC 双构**（共用头最容易在另一条工具链上静默变味）；② 两条工具链各存一份 `Stack_Size`/`Heap_Size`（`.ld` 的 `_Min_*` 与 `arm/startup_*.s` 的 `AREA STACK/HEAP`），**且语义不同**——GCC 侧只是"守卫预留"（栈从 RAM 顶向下长，偏小永不报错），Keil 侧是"固定实体块"（越界即踩坏相邻静态数据）。⇒ **同一份源码 GCC 正常、Keil 进 `HardFault` 就是这条**，按 Keil 的硬上限给足余量，**别拿 GCC 的数当基准**。

**无 `--gc-sections` 的第二重后果：应用必须补上第三方库"声明由应用实现"的弱钩子**。TinyUSB 在 `CFG_TUSB_OS=OPT_OS_NONE` 下要求应用提供 `tusb_time_millis_api()`（被 `tusb.c` 的 `tusb_time_delay_ms_api` 引用）。GCC 因 `--gc-sections` 把引用方整段摘掉，符号从不出现在未定义列表里；Keil 直接报 `L6218E: Undefined symbol`。修法：在 `bsp/` 里真定义（裸机直接 `return HAL_GetTick();`）。同类模式见 `syscalls.c` 的排除（方向相反）。

**armlink 分散加载的三条硬语法**（写 `.sct` 前先记）：
1. **不支持嵌套 load region**。`RUN_REGION LOAD_REGION { ... }` 会报 `L6630E` / `L6226E` / `L6292E`。要「加载在 Flash、运行在 RAM」必须拆成**两个平级顶层 load region**，各带显式基址。
2. `+RG` 属性组合必须**逗号分隔**：`*( +RW, +ZI )`；写成 `+RW +ZI` 直接 parse 失败。
3. 段选择器**必须带点**：`*.o (.section_name)`；裸写 `*(SECTION)` 报 `L6231E: Missing module selector`。

**ARMCLANG 链接时的「区域符号」名取自执行域名**：执行域命名 `Image$$<ER>$$Base` / `$$Limit` / `Load$$<ER>$$Base` 里 `<ER>` 是**执行域的标签**，不是 load region 名。改名后必须回头核对 C 侧 `extern` 声明。`UNINIT` 只能挂执行域，挂 load region 报 `L6324W`。

## 判据与反模式

| 判据 | 反模式 |
|---|---|
| HAL 入组 `.c` 个位数~十几个（H7 全量约 80+），与 CMake 源集一致 | 整包导入 HAL：编译链接变慢、Flash 虚高、无关模块报错 |
| `grep -c "Drivers/CMSIS/Device" CMakeLists.txt` == 0 | 依赖官方 Device 树，startup 重复定义 |
| uvprojx 内 `syscalls.c` 计数 0，半主机抑制垫片在位且 `BKPT` 计数 0 | 把 GCC 垫片塞进 Keil；或删掉半主机抑制垫片（**延迟暴露**的 `BKPT` 停机，编译链接却全过） |
| 帧缓冲落在 DMA 可达域（H7 DCMI 仅可达 AXI SRAM） | 帧缓冲落 DTCM，DMA 静默失败 |
| 擦写引擎放 AXI SRAM，校验失败在擦写前 abort | 擦写引擎放 DTCM；失败仍继续擦写 |
| 分段镜像用 `fromelf --bincombined` 出单文件 | 多 load region 下用 `--bin`，只得到一堆分片 |
| 镜像里的 `BKPT` 逐一比对来源（DHCSR 守卫 vs 半主机） | 见到 `BKPT` 就断言半主机泄漏（TinyUSB 的 `TU_BREAKPOINT()` 会大量出现且无害） |
| 栈按 Keil 的**硬上限**给足（map 查 `startup_*.o(STACK)` 尺寸 + `__initial_sp`） | 拿 GCC 的 `_Min_Stack_Size` 当基准"对齐"；GCC 正常就认定 Keil 也该正常 |
| 混用 Keil 产物调试：OpenOCD 烧 `.hex`、gdb 只取 `.axf` 符号 | 让 gdb `load` 一个 `.axf`：其 LMA 是 RAM 地址 → 写进 RAM、复位后跑进 `HardFault` |

## 详细资料

- `references/cmake-ninja.md` — 交叉编译骨架、源集切分、设备层、链接脚本、Presets、Cortex-Debug、脚本族与 `.bat` 坑。
- `references/keil-port.md` — Keil 移植全流程：uvprojx 字段、分散加载、UV4 命令行与日志、坑表、验收红线。
- `references/openocd-flash-ui.md` — OpenOCD 烧录、双镜像 Bootloader 分区跳转、LVGL 多页面 UI 与 README 约定。
