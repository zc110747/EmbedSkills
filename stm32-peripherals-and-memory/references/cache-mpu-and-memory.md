# 缓存、MPU 与内存/总线域（STM32H7 / F4）

## 1. 核心原则：用 MPU 隔离，而不是关 D-Cache

> **D-Cache 保持开启。即便外设上了 DMA，也不全局关 D-Cache；**
> **正确做法是用 MPU 把 DMA 共享的那块 RAM 单独标记为非缓存区。**

- 外设若**没用 DMA**（CPU 直接搬外设内部 FIFO，如 SDIO 轮询模式），开 D-Cache
  完全无一致性问题。
- 上 DMA 时，**只**把 DMA 共享的 RAM 划成 non-cacheable，其余 RAM 仍 cacheable 享受加速。
- 全局 `SCB_DisableDCache()` 牺牲整个系统的内存带宽，是偷懒且错误的做法。

## 2. H7 内存 / 总线域（选址前提）

| 区域 | 地址 | 域 | 备注 |
|------|------|----|------|
| DTCM | 0x20000000 | D1（紧耦合） | **IDMA/BDMA 不可达**，只能 CPU 直访；适合低延迟数据 |
| AXI-SRAM | 0x24000000 | D1 | 512 KB，IDMA/BDMA 均可达；**通用 RAM / 栈 / 字体池首选** |
| SRAM_D2 | 0x30000000 | D2 | 288 KB，IDMA 可达 |
| SRAM4 | 0x38000000 | D3 | 64 KB；**SPI6 属 D3 域**，同域 BDMA 最顺、零总线争用 |

- **SDMMC1 内部 DMA（IDMA）**：可达 AXI-SRAM / D2 / D3，**不可达 DTCM** ⇒ SD 扇区缓冲放
  DTCM 会 DMA 出错。
- **SPI6 显示（D3 域）**：DMA 走 BDMA，像素缓冲放 SRAM4 最顺。
  但 240×240×2 ≈ 115 KB 放不下 64 KB 的 SRAM4 ⇒ SPI6 DMA 只能做**行/块流式发送**
  （如 1~4 KB 行缓冲），不能做整帧帧缓冲。

## 3. MPU Region 规划草案（SDMMC IDMA + SPI6 DMA 场景）

| # | Base | Size | 属性 | 用途 |
|---|------|------|------|------|
| 0 | 0x24000000 | 512 KB | Normal Cacheable(WT/WB) | 通用 RAM / 栈 / 字体池 |
| 1 | 0x30000000 | 16 KB | Normal **Non-cacheable** | SDMMC IDMA 扇区缓冲 |
| 2 | 0x38000000 | 16 KB | Normal **Non-cacheable** | SPI6(BDMA) 显示发送缓冲 |
| 3 | SRAM_D2 余下 | 余下 | Cacheable | D2 其他数据（可选） |

关键点：

- Region1/2 标 non-cacheable 后，CPU 与 DMA 看同一份内存，**无需手工
  `SCB_CleanDCache` / `SCB_InvalidateDCache`** —— 这是选 non-cacheable 的核心收益。
- Region1/2 与 Region0 **不同 bank、不重叠** ⇒ MPU region 优先级不参与判断。
- 配套改动：链接脚本增两个 NOLOAD 段（分别定址到 RAM_D2 / RAM_D3）；
  C 侧用 `__attribute__((section("..."), aligned(16)))` 定义缓冲；`MPU_Config()` 里把
  Region1/2 的 MAIR 设为 non-cacheable；读写路径改成 DMA 版本并接完成回调。

## 4. 反查"是否真用了 DMA"（不要信注释）

代码注释常与实现矛盾，**只认代码**：

1. SD 读路径：`HAL_SD_ReadBlocks()` = 轮询（CPU 搬 FIFO，非 DMA）；
   `HAL_SD_ReadBlocks_DMA()` = IDMA。搜索工程确认真实调用点。
2. SPI 发送：`HAL_SPI_Transmit()` = 阻塞/轮询；`HAL_SPI_Transmit_DMA()` = DMA。
3. 缓存状态：是否调用过 `SCB_EnableDCache()`；MPU Region0 是否把 AXI-SRAM 标 cacheable。
4. **结论自洽检查**：若"非 DMA + D-Cache 开" ⇒ 无一致性问题，现状正确，不要关缓存。

> 实测案例：某工程实际调用了 `SCB_EnableDCache()`，SD 走 `HAL_SD_ReadBlocks()` 轮询，
> 注释却写"D-Cache 关 / SD 用内部 DMA" —— 注释是过时错误，被代码推翻。

## 5. 何时才需要落地 MPU non-cacheable 区

- SD 轮询 + D-Cache 开：**无需改动，方案可用**。
- 仅当把 SD 切 `ReadBlocks_DMA`、或 SPI6 切 `Transmit_DMA` 时，才按第 3 节划 non-cacheable 缓冲
  （缓冲大小、SRAM 选址、是否现在落地需与硬件负责人共同定稿）。
- 桥接类 DMA 缓冲在 D-Cache 开启时：要么按本节配 MPU 区域，要么在 DMA 前后做
  clean/invalidate；**不可既开 Cache 又什么都不做**。

## 6. 其他与"内存可达性"绑定的选址结论

- **ETH RX 零拷贝缓冲必须留内部 SRAM**：ETH DMA 写外部 SDRAM 会在分片突发时丢包
  （大包 ping 起就不稳定），memp 池同理放 SRAM；发送侧放 SDRAM 无碍。
- 外部 SDRAM（FMC）承载 RTOS heap / 协议栈池 / 显示缓冲时，**SDRAM 初始化必须早于任何
  RTOS 对象**（详见 `storage-and-filesystems.md`）。
- F4 的 CCM（0x10000000）与主 SRAM 不连续，且 ETH/DMA 不可达。

## 7. DTCM / Flash 的可执行性（H7 双 Bank 升级要点）

- **Cortex-M7 的 I-Code 总线无法从 DTCM(0x20000000) 取指**：把"从 RAM 执行"的擦写引擎
  放进 DTCM，一调用即 BusFault。引擎必须放 AXI-SRAM(0x24000000) 或其他可执行 RAM；
  MPU 的 XN 位管不了 TCM 的硬件约束。
- H7 内部 Flash 是**双 Bank（16×128KB）**：擦/写某 bank 时 CPU 不能从该 bank 取指，
  擦写引擎及**整条调用链**（含 static helper）都要带 RAM 段属性。
- H7 的 read-while-write 只会让总线**停滞而不 HardFault**——这解释了为何位于 Flash 的
  HAL 擦写原语仍可被调用。
- 优先用 HAL 原语而非手搓 `FLASH->CR`（自动处理 PSIZE 与时序）；每次操作前清双 Bank 错误标志；
  用关中断 + `HAL_FLASH_Unlock()` 包住，`HAL_FLASH_Lock()` + 开中断收尾。
- 擦除按 App 实际长度分两阶段（先擦非末扇区，末扇区在编程前即时擦），避免整片先擦后中途掉电变砖。
- 跳转 App 前必须：`HAL_DeInit` / 关全局中断 / 关 MPU / 关 I-D Cache / 设 MSP / 重定位 VTOR /
  清 PRIMASK。App 工程必须自带 `SysTick_Handler` 且 `main()` 开头开中断，否则 `HAL_Delay` 卡死。
