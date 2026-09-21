# 板级引脚映射与总线（参考板实测值）

> 引脚映射属于**板级信息**：换板后必须重新核对原理图与复用表。以下为参考板实测结果，
> 芯片/外设/器件型号保留，工程目录、主机端口号、脚本名一律不记录。

## 1. STM32H743ZIT6（HSE 25MHz 无源晶振）

| 功能 | 引脚 | 备注 |
|---|---|---|
| 调试串口 USART1 | PA9(TX)/PA10(RX) | 115200 8N1；主机端口号由系统分配，不可写死 |
| 状态 LED | PG7 | 低电平点亮 |
| USB FS | PA11(D-)/PA12(D+) | OTG_FS 内部 FS PHY；HS 走 PB14/PB15 |
| QSPI(W25Q64) | CS=PG6/AF10, CLK=PF10/AF9, IO0=PF8/AF10, IO1=PF9/AF10, IO2=PF7/AF9, IO3=PF6/AF9 | 4 线 |
| SDMMC1 4-bit | CK=PC12, CMD=PD2, D0-D3=PC8-PC11 | 轮询模式更稳；卷名见 `storage-and-filesystems.md` |
| SPI6(OLED ST7789) | SCK=PG13/AF5, MOSI=PG14/AF5, CS=PG8(软), DC=PG15(软), BL=PG12(软) | 4 线 SPI，240×240 |
| DCMI(OV5640) | HSYNC=PA4, VSYNC=PG9, PCLK=PA6, D0-D7=PC6/PC7/PG10/PG11/PE4/PD3/PE5/PE6；I2C_SCL=PF14, I2C_SDA=PF15, PWDN=PF13(低有效) | 见 `camera-and-display.md` |

时钟：HSE 25MHz → PLL1 → SYSCLK 480MHz / HCLK 200MHz / APB 100MHz。

## 2. STM32F429IGT6（HSE 25MHz）

| 功能 | 引脚 | 备注 |
|---|---|---|
| 调试串口 USART1 | PA9(TX)/PA10(RX) | 115200 8N1 |
| LED | PB0/PB1 | 低电平点亮（PB1 作心跳） |
| BEEP | I/O 扩展器 PCF8574T 的 P0 | 低电平发声 |
| SDMMC(SDIO) | SCK=PC12, CMD=PD2, D0-D3=PC8-PC11 | 4-bit |
| ETH(LAN8720A) | MDC=PC1, RXD0=PC4, RXD1=PC5, REF_CLK=PA1, MDIO=PA2, CRS_DV=PA7, TX_EN=PB11, TXD0=PG13, TXD1=PG14（RMII，PHY addr 0） | 复位经 I/O 扩展器位（高有效，经三极管反相后写 1 为释放） |
| I2C（共用） | SDA=PH5, SCL=PH4 | 挂 PCF8574T(0x20)/AP3216C(0x1E)/MPU9250(0x68)/AT24C02(0xA0) |
| FMC SDRAM(W9825G6KH-6) | 16bit D0-15、A0-12、BA0-1；SDNWE=PC0, SDNCAS=PG15, SDNRAS=PF11, SDNE0=PC2, SDCKE0=PC3, SDCLK=PG8 | Bank1 @0xC0000000，32MB |

时钟：HSE 25MHz → PLL M=25 N=360 P=2 Q=8 → 180MHz（OverDrive + FLASH_LATENCY_5）。

**F4 内存边界（选址前提）**：连续 SRAM 只有 192K（0x20000000~0x2002FFFF）；
CCM 64K @0x10000000 与主 SRAM 不连续，且 ETH/DMA **不可达**。

## 3. I2C：挂载与总线锁死恢复

从设备拉低 SDA 会锁死总线（噪声、复位中途打断事务），HAL 传输永久超时、读数冻结为 0。
不恢复则"一次失败"退化成"永久失败"。恢复流程缺一不可：

1. 检测 SDA 低 / BUSY / AF-ARLO-BERR **任一**成立才动手；
2. SCL 切 GPIO 推挽翻转 **≥9 次**释放从机，SDA 释放即提前停；
3. 在 SCL 高时发 STOP（SDA 低→高）；
4. `HAL_I2C_DeInit` + `Init` 清锁存标志；
5. 还原 AF_OD 与总线时序；
6. 复查 BUSY / SDA。

- 全程用 `__NOP()` 延时，**调度器启动前调用也安全**。
- 轮询式 HAL 传输的调用方防护：超时放大（10→50 ms）+ `vTaskSuspendAll()` 包成原子操作 +
  失败先恢复总线再立即重试一次。

## 4. UART 物理层与流控（CDC↔UART 透明桥）

三个坑全部来自"物理层/寄存器语义"，与业务逻辑无关：

- **环形缓冲满/空二义性**：`head == tail` 既表示空也表示满；若按 `cap - used` 算可用容量，
  会把"满"误判为"空"并覆盖未消费数据。可用容量必须取 `cap - 1`（故意少用一个字节）。
- **7 数据位 + 校验时校验位污染数据**：STM32 字长含校验位，7 数据位 + 校验 = 8 位字长（`M=00`），
  此时 RDR 的 bit7 就是校验位，按字节搬运会把它一起读入。
  按数据位算掩码 `(1 << data_bits) - 1`，在排空时对已消费缓冲就地掩蔽。
  现象特征：**7N1 通过，7E1/7O1 全失败**；8E1/8O1 不受影响（9 位字长，校验落在 bit8）。
  另注意 7 数据位模式无法承载任意二进制，只能用 7 位安全 ASCII 验证。
- **RTS/CTS 引脚模式必须与 `HwFlowCtl` 成对**：RTS 配 `AF_PP` 而 `HwFlowCtl=NONE` 时 USART 不驱动该脚，
  且复用模式下写 BSRR 无效 → 引脚高阻悬空，对端 CTS 被牵连读成"未就绪"，一帧不通。
  推荐 RTS 用 `OUTPUT_PP` 由软件按接收环余量驱动（硬件 RTS 只跟踪 1 字节 RDR 标志，对 KB 级 ring 无意义）；
  CTS 用 `AF_PP` + PULLDOWN（悬空读作就绪，对端主动拉高才暂停 TX，即标准透明行为）。
  流控做成连接门控（端口打开时使能 CTSE + 软件驱动 RTS），断开还原默认 8N1 无校验。
- **Windows `usbser.sys` 只转发 DTR 不转发 RTS**：`SETRTS/CLRRTS` 不触发 CDC 线状态回调，
  "由主机 RTS 切换流控"在 Windows 上位机不可行 ⇒ 流控必须固件自管理（主机驱动限制，非固件缺陷）。

## 5. USB 物理链路与供电（H7 枚举失败最高频坑）

- 座子接的是哪个控制器要按原理图确认：默认 OTG_FS(PA11/PA12) 用内部 FS PHY，
  实际连 PB14/PB15 则须改用 HS 预设。
- **根因多为 VDD33USB 供电未就绪**。OTG 收发器由 VDD33USB 域供电，必须二选一：
  使能片内 LDO（`PWR_CR3_USBREGEN`）或板卡把 VDD33USB 直连外部 3.3V（此时关 REGEN）；
  然后**必须**调 `HAL_PWREx_EnableUSBVoltageDetector()` 并等 `PWR_FLAG_USB33RDY` 就绪。
- 上电心跳可快速分段：不闪 = 没启动（查 HSE）；闪若干下后停 = 卡在 USB 供电；
  闪若干下后常亮 = 已枚举。
- 换能传数据的线（不少充电线只有 VBUS+GND）；避免中间接 Hub；CMSIS-DAP v1 是 HID 免驱。

```c
#if USE_INTERNAL_USB_REGULATOR          /* 外部直连 3.3V 时不要置位 */
  PWR->CR3 |= PWR_CR3_USBREGEN;
#endif
HAL_PWREx_EnableUSBVoltageDetector();
while (!__HAL_PWR_GET_FLAG(PWR_FLAG_USB33RDY)) { }
```

## 6. 自研 CMSIS-DAP 探针的接线与时序

- SWD 目标线（H7 为例）：SWCLK=PA0 / SWDIO=PA1 / nRESET=PA2 / SWO=PA3 / 目标供电检测=PA7。
- **三类线勿混**：烧写线、USB 上行线、SWD 目标线是三条独立链路，接错表现为"能枚举但不识别目标"。
- SWD 时序延时不要用 Keil 的 `__asm _DELAY`，改用 DWT 周期计数做精确延时。
