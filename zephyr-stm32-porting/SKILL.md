---
name: zephyr-stm32-porting
description: 在 STM32 上用 Zephyr 移植显示与外设：west 构建、设备树 overlay、LVGL 集成、GBK 点阵字库与 ST7789 点亮。适用于"Zephyr 移植""设备树 overlay""LVGL 集成""ST7789 全黑"等请求。
agent_created: true
---

# Zephyr + STM32 移植（显示 / 外设 / 字库）

把裸机外设（SPI 屏、SDMMC + FatFs、调试串口、点阵字库）搬进 Zephyr RTOS 时的差异点与坑。
配套 `embedded-windows-toolchain`（west / 工具链）、`stm32-build-and-scaffold`（工程骨架）。

## 何时用

- 用 Zephyr 在 STM32 上跑 LVGL + SPI 屏 + SD 卡字库
- 写/调设备树 overlay：时钟树、SPI/MIPI-DBI 屏、SDMMC、USART shell
- west 构建报工具链错误、删 `build/` 后重建失败、PowerShell 红字误报
- 屏全黑、LVGL 野指针、中文错位或显示成方框

## 核心知识点

- **west 入口**：`west` 不在 PATH 时用 `python -m west build -b <board>/<soc> -d build -s .`；
  `-b` 不能省，删 `build/` 后尤其。`ZEPHYR_BASE` 优先取环境变量，未设回退工作区内 `zephyr/`；
  MSYS2 下手动 export 要用 Windows 风格绝对路径。
- **配置走设备树**：时钟树（HSE 频率、PLL M/N/Q）、SPI 屏、SDMMC、串口都在 overlay 覆盖，
  不改驱动代码。
  - SDMMC 时钟源（PLL1Q）必须凑到 48 MHz，否则 FatFs `f_mount` 返回 `FR_NOT_READY`。
  - Zephyr FatFs 用字符串卷名（`CONFIG_SDMMC_VOLUME_NAME` + `FF_STR_VOLUME_ID`），盘符形如
    `SD:`，与裸机的数字盘符不同。
- **SPI 屏默认不亮**：驱动初始化不发 `DISPON(0x29)`，面板停在 sleep-in，应用需显式
  `display_blanking_off()`。
- **软件复位延时**：面板无硬件 RST 时驱动走 SWRESET + 极短延时，后续初始化命令（含 SLPOUT）
  被忽略 → 仍全黑，需 patch 驱动加长延时；patch 会被 `west update` 覆盖。
- **LVGL 内存池**：Zephyr 模块默认仅 2 KB，创建几个控件即野指针 / 总线错误，调到 64 KB。
- **LVGL tick**：`lv_conf.h` 启用 `LV_TICK_CUSTOM`，由 `k_uptime_get_32()` 供时；应用只周期调
  `lv_timer_handler()`，不调（也调不了）`lv_tick_inc()`。
- **GBK 字库**：SD 卡上"索引 + 点阵"分离；索引文件是双段结构（Unicode 升序段 + GBK 升序段），
  不能整体二分；GBK 字段小端存储，取出后要交换字节序。
- **shell 控制台**：`CONFIG_SHELL=y` + dts `zephyr,shell-uart`，命令用 `SHELL_CMD_REGISTER`
  注册，整个文件可跨工程复用。

## 判据与反模式

- 判据：串口启动日志出现 Zephyr 版本行 + 字库自检行 + 主频自检行；心跳 LED 周期翻转；halt 后
  PC 落在屏刷新路径（如 `mipi_dbi_spi_write_helper`）而非 fault handler。
- 判据：`west build` 以**退出码**判定成败，PowerShell 把 stderr 进度渲染成红字不等于失败。
- 反模式：在应用里硬编码时钟 / 引脚数值（应进 overlay）；按裸机习惯用数字盘符；指望
  `west update` 后 patch 还在；删了 `build/` 重建却不传 `-b`。
- 反模式：缺字时静默回退空白的 UI 必须显式提示"字库未加载"，否则会被误判成渲染 bug。

## 详细资料

- `references/devicetree-overlays.md` — 时钟树 / PLL、SPI 屏、SDMMC + FatFs、USART shell 的
  完整 overlay 与 Kconfig 片段
- `references/display-and-fonts.md` — 屏点亮与驱动 patch、GBK 双段索引结构、
  unicode→GBK→转置 桥接、LVGL 内存与 tick、shell 命令、Cortex-Debug
- `references/build-and-toolchain.md` — west 构建、CMake 工具链自动探测、删 `build/` 重建、
  一键脚本与 PowerShell 陷阱
