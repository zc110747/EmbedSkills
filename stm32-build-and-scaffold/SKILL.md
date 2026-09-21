---
name: stm32-build-and-scaffold
description: STM32 工程的统一骨架与构建规范：CMake+Ninja 交叉编译、HAL 按需引入、Keil MDK 移植、OpenOCD 烧录。适用于"新建 STM32 工程""搭 CMake 构建""移植到 Keil""链接报未定义 HAL 符号"等请求。
agent_created: true
---

# STM32 工程骨架与构建

一套目录分层 + 两套构建后端（CMake/Ninja + arm-none-eabi-gcc、Keil MDK-ARM）。配套 `embedded-windows-toolchain`、`embedded-verification-acceptance`。

## 何时用

- 新建或整理工程骨架、CMake 构建、Presets、Cortex-Debug。
- 移植到 Keil MDK-ARM（uvprojx + 分散加载）或用 UV4 构建。
- 编译慢、Flash 虚高、链接报未定义 `HAL_XXX_Init`。

## 核心知识点

**目录分层**：`app/`（应用）· `bsp/`（板级驱动）· `Drivers/`（ST 官方 HAL/CMSIS，不手改）· `sys_startup/`（本地设备层）· `third_party/` · `cmake/` · `tools/`。驱动按归属放对应目录，不混放。

**设备层必须本地化**：startup 向量表、`system_<系列>xx.c`、device 头、`*.ld` 一律放工程内 `sys_startup/`，不依赖 `Drivers/CMSIS/Device/...` 官方树——整树收集会重复定义 `Reset_Handler`/`SystemInit`，并把 iar/arm 语法喂给 GCC。

**HAL 按需引入**：禁止 `GLOB` 整目录收集 HAL 驱动，按代码里的 `HAL_XXX_` 反查模块只列所需 `.c`。任何工程都含 `hal.c`/`hal_cortex.c`/`hal_rcc.c`/`hal_rcc_ex.c`（+ `hal_gpio.c`）；H7 的 RCC/FLASH/DMA/TIM/PWR 须连 `_ex.c` 一起带。**新增外设时 CMake 源集与 uvprojx 的 HAL 组同步补齐**，否则链接未定义。

**CMake**：`add_executable` 的 startup / `system_*.c` 显式列出，不用 `GLOB_RECURSE` 整树收集；`file(GLOB ...)` 在配置期展开并缓存，**新增 `.c` 必须重跑 `cmake`**（Ninja 增量不会重扫）；改 `.ld` 靠 `LINK_DEPENDS` 才触发重链。栈顶 `_estack` 与 `RAM LENGTH` 按芯片真实容量，外部内存段必须 `(NOLOAD)`。

**工具写裸名、路径写相对**：`openocd` / `arm-none-eabi-gdb` / `arm-none-eabi-gcc` 走 PATH；`configFiles`/`svdFile` 用 `${workspaceFolder}` 指向工程根；不写安装目录、环境变量路径、绝对路径（换机器即失效）。`*.svd` 与 `openocd.cfg` 放工程根（与 `.vscode` 同级）。

**FreeRTOS**：startup 的 SVC/PendSV/SysTick 向量**直指** `vPortSVCHandler`/`xPortPendSVHandler`/`xPortSysTickHandler`；SysTick 被独占会冻结裸机 `HAL_Delay` 时基，需另配时基（如 HAL timebase 改到定时器）。

**OpenOCD**：0.12 用 `transport select swd`，不支持旧 `hla_swd`；H7 用 `stm32h7x.cfg`、F4 用 `stm32f4x.cfg`。`[find ...]` 脚本缺失/路径错属配置错误；"no probe attached" 类 adapter 报错属正常（需真机）。

**Keil 侧的反向约定**：`syscalls.c`（GCC/newlib 垫片）**必须排除**；半主机抑制垫片（`__use_no_semihosting` + `_sys_exit`/`_ttywrch`）**必须保留**——两者方向相反，极易搞错。`uThumb=1`/`thumb=1` 必开（Cortex-M 只认 Thumb）。ARMCLANG 警告参数用**单横杠** `-Wno-...`。Keil 全量入组会真的链进代码（无 `--gc-sections` 兜底）。

## 判据与反模式

| 判据 | 反模式 |
|---|---|
| HAL 入组 `.c` 个位数~十几个（H7 全量约 80+），与 CMake 源集一致 | 整包导入 HAL：编译链接变慢、Flash 虚高、无关模块报错 |
| `grep -c "Drivers/CMSIS/Device" CMakeLists.txt` == 0 | 依赖官方 Device 树，startup 重复定义 |
| uvprojx 内 `syscalls.c` 计数 0，半主机抑制垫片在位且 `BKPT` 计数 0 | 把 GCC 垫片塞进 Keil；或删掉半主机抑制垫片（**延迟暴露**的 `BKPT` 停机，编译链接却全过） |
| 帧缓冲落在 DMA 可达域（H7 DCMI 仅可达 AXI SRAM） | 帧缓冲落 DTCM，DMA 静默失败 |
| 擦写引擎放 AXI SRAM，校验失败在擦写前 abort | 擦写引擎放 DTCM；失败仍继续擦写 |

## 详细资料

- `references/cmake-ninja.md` — 交叉编译骨架、源集切分、设备层、链接脚本、Presets、Cortex-Debug、脚本族与 `.bat` 坑。
- `references/keil-port.md` — Keil 移植全流程：uvprojx 字段、分散加载、UV4 命令行与日志、坑表、验收红线。
- `references/openocd-flash-ui.md` — OpenOCD 烧录、双镜像 Bootloader 分区跳转、LVGL 多页面 UI 与 README 约定。
