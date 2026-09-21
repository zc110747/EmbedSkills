---
name: stm32-peripherals-and-memory
description: STM32(H7/F4) 外设驱动与缓存/MPU 一致性判据：引脚映射、DCMI/SPI 屏/SD/QSPI/USB 实测坑、DMA 缓冲选址。适用于"引脚映射""D-Cache 要不要关""MPU 怎么配""DMA 缓冲放哪"等请求。
agent_created: true
---

# STM32 外设与内存：知识点与判据

面向 STM32H743 / STM32F429 的外设驱动、板级接线与缓存/MPU 一致性判据。结论来自真机验证；
换板后引脚映射与缓冲选址必须重新核对。

## 何时用

- 配置或排查 DCMI/OV5640、SPI 屏(ST7789)、SD/SDMMC、QSPI Flash、USB OTG_FS 与 USB Host、
  ETH(RMII)、I2C、FMC SDRAM、电容触摸(GT911)。
- 决策"D-Cache 要不要关""DMA 缓冲放哪块 RAM""MPU region 怎么划"。
- 现象为"驱动能编译但设备不工作 / 丢数据 / 撕裂 / 花屏 / 中文乱码 / 中断风暴"。

## 核心知识点

| 知识点 | 结论 |
|---|---|
| D-Cache | 保持开启，绝不全局 `SCB_DisableDCache()`；上 DMA 时用 MPU 只把 DMA 共享 RAM 标 non-cacheable |
| non-cacheable 收益 | CPU 与 DMA 直接看同一份内存，免除手工 clean/invalidate |
| H7 域可达性 | DTCM 只能 CPU 直访（IDMA/BDMA 不可达）；SPI6 属 D3 域走 BDMA，缓冲放 SRAM4 最顺 |
| 缓冲选址 | 按"域 + DMA 可达性 + 缓冲大小"决定，不按习惯；整帧装不下同域 RAM 时改行/块流式发送 |
| 外设基地址 | 同名外设跨系列地址不同（H7 的 DCMI 是 0x48020000，不是 F4 的 0x40050000），一律查手册并用 DMA 的 PAR 交叉验证 |
| 中断源 | 逐字节排空选 TXE；只有"线路空闲"语义（如 RS485 方向切换）才用 TC |
| 中断上下文 | ISR 内不调用会取锁/会阻塞的日志宏，改用无锁缓冲写接口 |
| 中断风暴 | 解法是切断噪声源（引脚上拉）+ ISR 内自屏蔽 + 任务侧延时重武装，不是在 ISR 内软件滤波 |
| 编码 | FatFs `FF_CODE_PAGE=936` 承载 GBK，改小会让中文路径乱码；渲染前先判"无 BOM 合法 UTF-8"再决定是否转码 |
| 卷名 | 挂载名由 FatFs 配置（卷名字宏 / `FF_VOLUMES` 顺序）决定，不可跨平台照搬 |
| 颜色字节序 | emWin(`GUI_USE_ARGB=0`) 为 0x00BBGGRR，LVGL 为 0x00RRGGBB，跨库比对像素前先做 R/B 交换 |

## 判据与反模式

- **先核对板级原理图再定引脚映射**：外设实例与复用随板而异，本 skill 只给参考映射。
- **先反查代码再信注释**：搜 `HAL_xxx_DMA(...)`、`SCB_EnableDCache()` 才能确认是否真用 DMA、
  缓存是否开；注释与实现矛盾时以代码为准。
- **设备完全不工作时按三段定位**：供电/复位 → 总线通信 → 数据通路，不要先改业务代码。
- 反模式：为 DMA 正确性关全局 D-Cache；把 DTCM 当 DMA 缓冲或 RAM 执行区；
  硬编码屏幕画布尺寸而不按 GUI 库接口取分辨率；给"7 数据位 + 校验"链路按字节直接搬运；
  跨 GUI 库直接复用颜色字面量。

## 详细资料

- `references/pin-maps-and-buses.md` — 板级引脚映射、时钟、F4 内存边界、I2C 锁死恢复、
  UART 物理层与流控、USB 接线与 VDD33USB 供电、CMSIS-DAP 探针接线。
- `references/camera-and-display.md` — DCMI/OV5640 采集与撕裂根因、ST7789 SPI（含 Zephyr 差异）、
  emWin 栈、F429 LCD 8080、GT911 触摸与中断风暴三层防护。
- `references/storage-and-filesystems.md` — QSPI Flash、SD/FatFs、GBK 点阵字库双段结构、
  编码判定、exFAT、U 盘与 FatFs 并发。
- `references/cache-mpu-and-memory.md` — H7 内存域与 MPU region 草案、DMA 缓冲选址、
  ETH RX 选址、DTCM/Flash 可执行性与 H7 双 Bank 升级要点。
- 日志系统（环形缓冲、RTOS 双 TX 路径）以 `mcu-logging` 为准。
