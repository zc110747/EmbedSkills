---
name: ra8d1-fsp-platform-notes
description: RA8D1（R7FA8D1BH / Cortex-M85）FSP 平台：内存映射、GLCDC 与 MIPI DSI、xSPI/OSPI（r_ospi_b）、SDRAM、SWD 取证。症状：显屏不出图、OSPI 读不到 ID。
agent_created: true
---

# RA8D1 / FSP 平台经验（跨项目，不含具体工程）

> 适用：Renesas RA8D1（R7FA8D1BH，Cortex-M85 @480MHz）+ FSP。所有结论来自实测（SWD 读寄存器 / 串口 / 官方生成代码），
> 未验证项须标「待确认」，禁止用模板默认值冒充芯片真值。

## 1. 芯片与内存映射（凭实据，勿信 Studio 模板）

- **时钟源以生成代码为准**：Studio 模板 `source_freq=8MHz` 常是占位值；实际板子 `bsp_clock_cfg.h` 多为 **XTAL=20MHz**。
  PLL1 = XTAL×48 = 960MHz → CPU = PLL1P/2 = **480MHz**；PLL2 同理，PLL2R/2 = **240MHz → LCDCLK**（GLCDC 像素时钟源）。
- **内存区域（区域上限，非实贴容量）**：
  - Code Flash 2MB @ **0x02000000**（FSP 常用长度 0x1F8000，顶部保留）
  - SRAM 1MB @ **0x22000000**（BSP 实用区常 0xE0000 = 896KB）
  - ITCM 64KB @0x00000000 / DTCM 64KB @0x20000000 / Data Flash @0x27000000（保留 0x3000）
  - QSPI Flash @ **0x60000000**；**SDRAM @ 0x68000000**（16-bit 总线，区域上限 0x8000000）
- **冲突判据**：BSP 描述文件（yaml）里的容量常与代码 Kconfig 不一致（如写 32Mb 实为 32MB）。
  **以链接脚本 + BSP 代码为准**，再用实测（写读回）最终确认。

## 2. 工具链与烧录调试链

- 编译：`arm-none-eabi-gcc` + CMake + Ninja。Cortex-M85 参数实测可用：
  `-mcpu=cortex-m85 -mfpu=auto -mfloat-abi=hard -mthumb`。
- **pyOCD 烧录（推荐）**：`-t cortex_m` 泛型目标 + 官方 DFP pack 里的 FLM 闪存算法。
  - RA8 pack 的**具名 target（如 r7fa8d1bh）在部分 CMSIS-DAP 探针上初始化必失败**
    （`DebugPortSetup` → `SWD/JTAG communication failure (No ACK)`）；`pack.debug_sequences.enable=false`、
    `disabled_sequences`、`deferred_transfers`、`limit_packets`、under-reset 等组合都无效。
  - **正解**：用泛型 `cortex_m` + 手动注入 `FlashRegion(flm=官方 FLM)`，用官方算法擦写。
  - **RA8D1 要配 4 个 flash region / 4 个 FLM**（覆盖 ELF 里**全部带内容的 `PT_LOAD` 段**；
    少一个，gdb `load` 就整段中止，而 `pyocd flash` 只是警告跳过）：

    | region | 地址 / 长度 | FLM |
    |---|---|---|
    | code flash | `0x02000000` / `0x1F8000` | `RA8D1_2M.FLM` |
    | code flash config（选项字节） | `0x0300A100` / `0x200` | `RA8D1_CCONF.FLM` |
    | data flash | `0x27000000` / `0x3000` | `RA8D1_DATA_C2M.FLM` |
    | data flash config | `0x27030050` / `0x3B0` | `RA8D1_DCONF.FLM` |

    RA8D1 全部 FLM 的算法 RAM 都是 `RAMstart=0x22000000, RAMsize=0x2000`（→ `region._RAMstart/_RAMsize`）。
    ⚠️ **`RA8D1_DCONF.FLM` 不在 pdsc 的 RA8D1 algorithm 列表里**（pdsc 只写了 1M/2M/CCONF/DATA_C1M/DATA_C2M）；
    想知道它覆盖哪段地址，只能解析 FLM 内的 `FlashDevice` 结构体（offset 132=DevAdr、136=szDev）。
    FSP 链接脚本里那个 `0x27030080` 的 `.option_setting_data_flash_s` 就归它管。
  - pack 修补：DFP 的 pdsc 有时引用不存在的 `_NS` FLM（pyOCD 加载失败）；SVD 的 dim 格式在旧版 pyOCD 上会崩 →
    预处理脚本去掉 missing algorithm 行 + svd 属性。
    （pyOCD 0.45.1 实测 `R7FA8D1BH.svd` 可正常加载，214 个外设，无需预处理。）
- **OpenOCD 调试**：sysprogs 构建版 0.12.0 **无 RA8 flash 驱动**（只含 renesas_rpchf）→ 只用于 halt/断点/复位/gdb server，不用于烧录。
- **⚠️ 烧录前必须 `reset_and_halt()`**：目标固件若开了 D-Cache，运行中烧录会 `FlashFailure: target was not halted`
  （DAP 写入算法 RAM 后 CPU 读到陈旧缓存行）。复位态缓存关闭即正常。
- **探针枚举不稳定**：部分 CMSIS-DAP 探针约 50% 概率枚举失败需重试；残留 openocd/gdb 进程要 kill 后再试。
- **ART-Link VCP 串口控制台（COM9 = SCI9 = uart9，TXD9=P209/RXD9=P208）抓启动横幅**：
  - 控制台设备名 `uart9`（RT-Thread `RT_CONSOLE_DEVICE_NAME`），FSP 算出的硬件波特率 = **115200**
    （brr=64、BGDM=1、CKS=3、480MHz/(64×65)=115384，误差 0.16%，与生成注释吻合）。
  - **⚠️ 用 pyserial 开 COM9 时必须 `ser.rts=False`（`dtr=True`）**：ART-Link 的 CDC-VCP 仅在 RTS 去断言时才把
    目标 SCI9 桥接到主机；默认 RTS 生效 → 整条线静默、0 字节（误判"固件没输出"）。
  - 抓取时序：`reset_and_halt()` → 开串口(rts=0) → `resume()` → 读 ~12s，即可拿到完整 RT-Thread 启动横幅与 `msh />` 提示符。
  - 不依赖串口的硬证据：pyOCD `read_memory_block8(0x02000000, used)` 读回整片 code flash，CRC32 与 ELF 解析出的
    镜像比对（本仓实测一致 `0x3C9FA284`）→ 证明烧录内容逐字节无误。

## 3. GLCDC + RGB 面板

- 数据通路：CPU 写 SDRAM framebuffer → GLCDC GR[n] 取数（RGB565）→ PCLK → TCON → 面板。
- **framebuffer 必须放 SDRAM**：单屏 800×480×2B ≈ 768KB，双缓冲 ≈1.6MB，远超片内 RAM。放 `.sdram` NOLOAD 段。
- **RGB565 行跨距 stride**（官方公式）：
  `STRIDE_BYTES = ((W*BPP + 0x1FF) >> 9) << 6`，`STRIDE_PIX = STRIDE_BYTES*8/BPP`。
  800×16bpp → 1664B；480×16bpp → 960B（此分辨率下恰等于 width，但别假设恒等）。
- PCLK = LCDCLK / DCDR（DCDR 从 PANEL_CLK.DCDR 读）；刷新率 = PCLK/(H_total×V_total)。
- 背光/复位常为 GPIO（如 P101x/P110x，以原理图为准）。
- **`BG.EN_b.VEN` 写 1 后读回 0 是正常的**：VEN 反映完成后硬件自清零，`EN` 保持 1 即健康态。
- **`STMON.L2UNDF` 良性伪影（FSP r_glcdc 固有）**：未使用的 layer2 若 `p_base==NULL`，
  `r_glcdc_graphics_layer_set` 提前 return、从不置 `GR[1].EN=1`，但 `R_GLCDC_Open` 尾部仍无条件给
  `GR[1].CLUTINT` 编程 line-detect LINE → `GR[1].MON.UNDFLST` 粘滞置 1 → `STMON.L2UNDF` 永久回显 1，
  任何 `STCLR` 在 1~2 帧内被重新拉起。**零功能影响，不要改上游**；验收判据只用 `L1UNDF==0`（layer1 真在取数）。

## 4. MIPI DSI 面板（GLCDC → DSI 桥接）

- 通路：GLCDC RGB565 输出 → DSI host（`r_mipi_dsi` + `r_mipi_phy`）→ 2 条 D-PHY lane 串行 → 面板。
- **面板需要 DCS 上电序列**（推命令，`ra8_mipi_*` 类封装），不是纯 RGB 上电即亮。
- 启动日志可核对：`[mipi] N DCS commands pushed, seq0=..., phy_status=0x0`。
- 状态可用 `R_MIPI_DSI_StatusGet`（link_status / ack_err）。

## 5. 硬件 RTC（FSP 常无 `r_rtc` 模块）

- **可能没有 FSP `r_rtc` 驱动** → 手写直接编程 `R_RTC @ 0x40202000`。
- 计数源需要 **32.768kHz 子时钟晶振**（XCIN/XCOUT）。可行性先查原理图确认晶振已贴 + 负载电容；
  代码侧需 `BSP_CLOCK_CFG_SUBCLOCK_POPULATED=1`，启动期 `bsp_clock_init()→bsp_sosc_init()` 会启动并稳定子时钟。
- 计数器为 **BCD**。寄存器：RSECCNT(0x02)/RMINCNT/RHRCNT(PM 位)/RWKCNT/RDAYCNT/RMONCNT/RYRCNT(0x0E)；
  控制 **RCR2(0x24)** bit0 START/bit1 RESET/bit6 HR24；**RCR4(0x28)** bit0 RCKSEL。
- 初始化：`PRCR` 解锁 → RCR4 选源 → RCR2.RESET 脉冲 → HR24=1 → 写计数器 → RCR2.START=1 → 锁 PRCR。
- **⚠️ `RCR4.RCKSEL` 语义与字面相反：`0 = 子时钟晶振`，`1 = LOCO（未校准内部 RC）`。**
  误置 1 会让 RTC 跑在 LOCO 上，走时飞快（实测快 10 倍量级）。正解置 0。
- **⚠️ SWD 直读 RTC 寄存器（0x40202000）常返回 0**：RTC 在 VBATT 域，调试器 APB 访问不可靠。
  **不要用 SWD 判 RTC 是否运行** —— 改用串口命令读时间、取前后差值测走时（如 60s 墙钟 ↔ RTC 秒差）。
- 无备份电池时冷复位回到编译期默认值；运行期可 `set` 校准。

## 6. SCI（UART / simple-I2C）

- **`IOPORT_CFG_NMOS_ENABLE`(0x40) 是 N 沟道开漏**：从别处抄引脚配置若误带此标志到 TX 脚，
  TX 永远拉不起来、串口 0 字节输出。抄 `pin_data.c` 时逐条核对 NMOS 只出现在该出现的位置。
- **SCI_B FIFO 模式下不能用 `TDRE` 做发送门控**：`CFG_FIFO_SUPPORT=1` 时 `CSR_b.TDRE` 只反映
  TDR↔移位寄存器握手、不反映 FIFO 是否满 → 轮询写静默溢出（现象：每次只出前 N 字符，N==FIFO 深度）。
  **正解**：用 `FTSR_b.T`（FIFO 计数，FTSR @0x54，T[5:0]）判断 `while (fifo_depth <= FTSR_b.T) ;`。
- simple-I2C（SCI）排查要点：`ICR` 的 IICINTM/IICCSC/IICACKT/IICDL；`ISR.IICACKR`(bit0) 判 NACK。
  从机不应答时，先确认引脚复用/地址/上拉，再用**手工位翻转 I2C（绕开 SCI）**独立验证总线。

## 7. ICU 向量表（FSP）

- ICU 是「事件 → slot」两表结构，**slot 序号 == NVIC IRQn**：
  ```c
  const fsp_vector_t g_vector_table[MAX]         = { [0] = xxx_isr, };
  const bsp_interrupt_event_t g_interrupt_event_link_select[MAX] = { [0] = BSP_PRV_IELS_ENUM(EVENT_SCIx_RXI), };
  ```
- **删驱动要同步删向量槽**：删掉某外设驱动后，若 `vector_data.c/.h` 仍引用其 ISR，会链接报
  `undefined reference to xxx_isr` → 移除对应 slot 并递减 `VECTOR_DATA_IRQ_COUNT`。
- `IELSR[]` 中断事件选择寄存器偏移较大（如 R_ICU_BASE `0x40006000` + **0x6300**）；
  **写错偏移会导致"读回全 0/无效"的假结论**——核对地址再下判断。

## 8. 引脚复用（PFS）与写保护

- `R_PFS_BASE = 0x40400800`；每端口 16 pin × 4B：**`PmnPFS = base + m*0x40 + n*4`**
  （常见错误：把步进当 0x10/0x100）。
- 关键位域：bit2 PDR(方向)、bit4 PCR、bit6 NCODR、bit16 PMR(外设模式)、**bits[28:24] PSEL(功能选择)**。
- **PFS 写保护走 TZ 路径**：解锁寄存器是 `R_PMISC->PWPRS @0x40400D14`（bit6 PFSWE），
  **不是** `PWPR@0x0C`。正常路径由 `R_BSP_PinAccessEnable/Disable` 完成（成对使用）。
- 外设宏参数名勿用 `pin`/`port` 之类会与 `.pin`/`.port` 指定符冲突的字，用 `_pin`/`_periph`，否则编译报
  `xxx has no member named 'BSP_IO_PORT_xx_PIN_xx'`。

## 9. xSPI / OSPI 串行 Flash（r_ospi_b 驱动陷阱）

**寄存器布局（`R_XSPI_Type`，勿靠猜/别记错 stride）**：
`WRAPCFG 0x00`、`COMCFG 0x04`、`BMCFGCH[2] 0x08`、**`CMCFGCS[2] 0x10`（stride 0x10）**、
**`LIOCFGCS[2] 0x50`（stride 4）**、`ABMCFG 0x58`、`BMCTL0 0x60`、`BMCTL1 0x64`、
`CMCTLCH[2] 0x68`、`CDCTL0 0x70`、**`CDBUF[4] 0x80`（stride 0x10）**、
`LPCTL0/1 0x100/0x104`、`LIOCTL 0x108`、
**`CCCTLCS[2] 0x130`（stride 0x20）**、`VERSTT 0x180`、**`COMSTT 0x184`**、
`CASTTCS[2] 0x188`（stride 0x20）、**`INTS 0x190`、`INTC 0x194`、`INTE 0x198`**。
> RA8D1 是**单 xSPI 单元 + 2 channel（=CS0/CS1）**，所以 `[2]` 数组的**索引就是 CS**，
> 不是两个独立单元。`[2]` 数组的第二元素偏移 = 首元素 + stride，**不是 +0x40**（曾因此读到全 0 而误判配置失败）。
> 常见漏项：`WRAPCFG` 漏进位（`CMCFGCS[2]` stride 是 0x10 不是 0x0C）→ 之后全部地址错位。
> **`COMSTT/INTS/INTE` 三个偏移极易记错**（曾写成 `0x164/0x170/0x178`，`0x164` 根本不是寄存器，
> 读回 0 会被当成"状态为 0"）。**唯一可靠来源是 `R7FA8D1BH.h` 结构体成员注释里的 `@ 0x...`**，
> 写任何 dump 代码前先 grep 一遍：
> `grep -nE 'uint32_t +(COMSTT|VERSTT|INTS|INTE|CMCFGCS|LIOCFGCS|CCCTLCS)' Include/R7FA8D1BH.h`
> 引号外再核对 `#define R_XSPI_XXX_Pos` 的位域定义确认字段语义。

**CS 通道 = 驱动 `channel` 字段，必须与物理 CS 一致**：
- `ospi_b_extended_cfg_t.channel = OSPI_B_DEVICE_NUMBER_0/1`。
- 驱动按 channel 索引 `LIOCFGCS/CMCFGCS/CCCTLCS`，并选 `BMCTL0` 的 `CH*CS1ACC` 位；
  手动命令用 `CDCTL0.CSSEL`（bit3）选 CS。**开错 channel = 配置到另一个 CS 上，现象是"寄存器全对但总线静默"**。
- **XiP 映射窗：CS0=0x80000000，CS1=0x90000000**（`BSP_FEATURE_OSPI_B_DEVICE_0/1_START_ADDRESS`）。
- ⚠️ **`r_ospi_b` 驱动 bug（CS1 场景必踩）**：`r_ospi_b_xip()` 进出 XiP 时把 `BMCTL0`
  **整体写常量** `READ_ONLY_VALUE=0x55` / `READ_WRITE_VALUE=0xFF`，而 `0x55=0b0101'0101`
  只保留 CS0 字段、**把 CS1 字段 [3:2] 清成 0b00（无访问权）**。
  ⇒ 用 CS1 时每次 XiP 切换后必须补 `R_XSPI->BMCTL0 |= CH0CS1ACC_Msk|CH1CS1ACC_Msk`。
  **症状**：手动命令路径（0x9F）能通，但 XiP 读 0x90000000 立刻异常。

**引脚确认（勿信生成器输出，以原理图为准）**：
- 网络名 → 引脚要**双向核对**（MCU 侧 ball→Pmn + 器件侧 pin→net），并用**固件自读** `PmnPFS`
  验证 `PSEL==0x1C`（`IOPORT_PERIPHERAL_OSPI`）+ `PMR==1` 真正写入。
  ⚠️ **不要用 pyOCD 读 `PmnPFS`** —— 实测读回全 0，与固件自读矛盾（见第 11 节）。
- **1S-1S-1S 模式下 `LIOCFGCS=0` 是正确结果**（PRTMD=0 + 三项 CS 时序全 0 扩展），不是"没写进去"。
- 参考工程 `pin_data.c`/生成器输出**可能是错的或属于别的板子版本**；用户给的引脚 + 原理图优先。

**Bit-bang 兜底（判定"控制器坏" vs "板上无芯片"）**：
把 6 个引脚改 GPIO，手打 `0x9F`。**必须同时把 `~WP`/`~HOLD` 拉高**，否则 W25Q 静默不应答。
注意引脚口径：`P100`=port1/pin0 而 `P104`=port10/pin4 —— 混用会静默打到别的脚。
⚠️ **bit-bang 后必须把 PSEL 写回**：`R_IOPORT_PinCfg()` **不写 PSEL 字段**
（其实现只在 PSEL 非 0 时先清 PMR，从不把 PSEL 置回），所以 GPIO 化后**重新 `Open()` 控制器也拿不回引脚**，
后续所有 xSPI 读都变成静默 `00 00 00`。正解：用 `R_IOPORT_PinsCfg()` 重写整张 OSPI 引脚表
（`pin_cfg = IOPORT_CFG_PERIPHERAL_PIN | IOPORT_PERIPHERAL_OSPI`）把所有 6 个脚的 PSEL 恢复。
**同一个坑也适用于任何"peripheral → GPIO → 想变回 peripheral"的流程。**

**MISO 线路体检（比读 ID 更有信息量，但要注意局限）**：
把 MISO 设 GPIO 输入，**先不带上拉采一次、再开内部上拉（`IOPORT_CFG_PULLUP_ENABLE=0x10`）采一次**：
| 无上拉 | 带上拉 | 结论 |
|---|---|---|
| 0 | **1（稳定）** | 线路完好，无器件驱动 ⇒ **芯片未贴/未供电/CS 未到达** |
| 0 | **0** | 被强拉低 ⇒ 短路或器件卡死在驱动低 |
| 1 | 1 | 有外部上拉且线路空闲（正常空闲态）|
> 无上拉时读 0 **不等于**短路 —— 板上没贴外部上拉时，未驱动的线本来就是 0。
> 必须做"开上拉"这一步才能区分「浮空」与「被拉死」。
> ⚠️ 该体检**用 GPIO 模式读输入脚**（不涉及外设驱动竞争），所以结果可信；
> 但**不能推广到"读外设正在驱动的脚"**——那种读法是竞争电平，见第 11 节。

**裁决顺序（省时间）**：① **固件自读** 6 个 `PmnPFS` 确认 PSEL/PMR → ② `ospi regs` 确认 channel 寄存器
（含 XiP 后的 `BMCTL0`）→ ③ MISO 上拉体检 → ④ bit-bang（WP/HOLD 拉高）→
⑤ **若 CS 是否断言无法在固件侧判定，直接上示波器/万用表**：
量 `~CE` 在命令瞬间有无下拉脉冲、`SCLK` 有无时钟沿、`VCC` 是否 3.3V。
> **别在固件里反复造"CS 监视器"**——`COMSTT.ECSCS` 不跟踪总线（实测 64 次命令恒值），
> `COMCFG.ECSINTOUTEN` 是输出使能不是回读使能。固件侧测不出就该停，换外部仪表。

## 10. Cache / MPU / DMA 一致性

- Cortex-M85 带 I/D-Cache；**GLCDC / CEU 等总线主设备直接读 SDRAM**，与 CPU 缓存不一致会读到陈旧数据。
- BSP 链接脚本常预留两个 NOLOAD 段供免一致性问题使用：`.nocache`（片内）与 `.nocache_sdram`（SDRAM 内）。
- **约定**：framebuffer 与 DMA 缓冲**要么放 `.nocache_sdram`（MPU 非缓存），要么严格成对 clean/invalidate 并写明理由**；
  禁止无解释地随手 clean/invalidate。
- 一致性结论要用寄存器读数（MPU/缓存配置）确认，不凭记忆断言。

## 11. SWD 取证方法论（无串口/无可视输出时）

- **SWD halt 会让串口 shell 失聪**（halt 后 RTOS msh 不再回显/收命令，但心跳仍打印）→ 取证完 resume 或复位恢复。
- 读外设/内存判据：`PmnPFS` 看引脚方向/复用是否生效；`IELSR`/`NVIC ISER` 看中断；外设寄存器看时序参数。
  但**VBATT 域（RTC）等区域 SWD 读不可靠**，改用串口间接测量。

- **⚠️⚠️ pyOCD 读 RA8D1 外设空间会返回全 0 —— 不能当证据。** 实测同一时刻：
  | 项 | 固件自读 | pyOCD SWD 读 |
  |---|---|---|
  | `PmnPFS`(P104) | `0x1C010C00` PSEL=0x1C PMR=1 | `0x00000000` |
  | `MSTPCRB` | `0xffbeffff`（XSPI 时钟**开**） | `0xffffffff`（"关"） |
  | 整个 `R_XSPI` | 非零 | 全 `0` |

  → 会得出"引脚没复用""时钟被门控"两个**完全错误**的结论。
  **判外设状态一律用固件自读**（加个 `xxx regs` shell 命令，或把值写进固定 RAM 结构体再 SWD 读 RAM）。
  SWD 只适合读 **RAM / 已确认可读的核外区域**。

- **仪表必须先对"已知答案"校验，再用来下结论。** 本项目在"CS 到底有没有拉低"上连错两版，
  根因都是拿未校验的仪表去测未知量：
  1. **把外设正在驱动的 pad 掰成输入去读** → 读到的是竞争电平，无命令时也读低 → 假阳性。
     读输出脚必须在**外设完全放开该脚**（PSEL 清 0）之后。
  2. **`COMSTT.ECSCS`** 看似"CS 监视器"，实测 64 次连续命令**恒为 `0x00770000` 一位未动**
     → 它不跟踪总线；且 `COMCFG.ECSINTOUTEN` 是 *ECS/INT **Output** Enable*（把信号**输出到引脚**），
     不是把 ECS 引到状态位。**读数与 CS 状态无关。**
  - 正确做法：先拿一个**能自己控制电平的引脚**验证读法（写 1 读 1、写 0 读 0），
    再拿它读未知引脚；仪表若在"必然有变化"的场景下**纹丝不动**，它就是不适用，而不是"信号卡住"。
  - 判据：**仪表在已知会变的场景下不变 = 仪表无效**，结论应停在"测不出"，不许外推。

- framebuffer 像素断言：读 SDRAM 里 framebuffer，用 `Counter` 统计色彩分布，
  断言设计色（RGB888→RGB565）出现、几何包围盒居中/落在设计带。

## 12. 上游 FSP 集成纪律

- 上游驱动**原样拷贝不改**；仅生成头文件（`board_cfg.h`/`bsp_mcu_family_cfg.h` 等）的相对路径按本仓调整。
- **按目录 GLOB 收集源文件 → 删目录/删文件即移除编译**；但**新增源文件后必须重新 configure 构建**
  （CMake `file(GLOB)` 不会自动追踪新文件，仅重跑 ninja 不够 → 链接报 undefined reference；
  彻底做法：清空重建构建目录，或加 `CONFIGURE_DEPENDS`）。
- 自研代码 `-Wall -Wextra` 严格零警告；上游以 `-w` 原样编译，零警告铁律不约束上游。
- **用链接器段表注册自身的框架（RT-Thread 的 `.rti_fn`/`FSymTab`、`__attribute__((constructor))` 等）
  不能打进静态库**：链接器只按"解决未定义符号"抽取成员，纯靠 section 注册的成员会被静默丢弃
  （现象：内核在跑但 shell 无回显）。要么直接编进 executable，要么 `--whole-archive`。

## 13. 待确认项处理原则

原理图 > Datasheet/User Manual > 官方 BSP 代码 > 其他。占位/模板值（如默认 XTAL、默认容量、
模板引脚名）一律不当真值；每一项硬件事实标注来源，未证实写「待确认」，用实测收口。
