# 摄像头与显示链路：DCMI/OV5640、ST7789、emWin、F429 LCD 8080、GT911

## 1. OV5640 (DCMI) 采集

### 1.1 寄存器与极性（真机踩坑）

- **DCMI 外设基地址在 H7 上是 `0x48020000`（AHB2）**，`0x40050000` 是 F4 的 DCMI 地址。
  读错地址不会报错、只会白耗时间；用 DMA 的 `PAR`（外设地址寄存器）交叉验证最直接。
- **极性**：PCK/VSYNC/HSYNC = `RISING / LOW / LOW`，对应传感器寄存器 `0x4740 = 0x21`。
- 传感器输出 `400×300 YUV422/YUYV`，再由 DCMI crop 到目标尺寸（如 240×240 / 192×192）。
- DMA：`DMA2_Stream1`（或 Stream7），`CIRCULAR` + `WORD` 对齐 + `FIFO FULL` + `INC4/SINGLE`。
- I2C 写 OV5640 寄存器走 SCCB 协议（电气兼容 I2C）；`PWDN` 低电平工作。
- **彩条模式 `0x503D=0x80` 是判断 DVP 故障段最快的方法**：能出彩条说明"传感器在输出、
  DCMI 没采样"，反之则是传感器侧问题。

### 1.2 撕裂根因与结构化解法

撕裂的根因几乎都是**在 DMA CIRCULAR 覆写缓冲的任意相位做 `memcpy`**。
用"采集/显示分离"结构从源头杜绝：采集侧硬件双（三）缓冲 + 一块只由 CPU 写的显示缓冲，
采集与显示/算法解耦。图像缓冲放在 DMA 可达、带宽足够的 RAM（如 H7 的 AXI-SRAM）。
分辨率按用途裁剪（人脸检测只需 96×96，先把图裁小再送算法）。

### 1.3 驱动来源建议

- ST BSP 的 ov5640 组件寄存器表有 bug（QVGA 表未使能水平 binning）。
- **优先提供已验证的参考驱动源码（含完整寄存器表）**，比让模型从零生成参数省时得多；
  从零生成的参数常卡在"能出图但尺寸/颜色不对"很久。

## 2. ST7789 (SPI) 显示

- 4 线 SPI：SCK/MOSI 走硬件 SPI，CS/DC/BL 用 GPIO 软件控制（引脚见 `pin-maps-and-buses.md`）。
- **Zephyr 移植差异**：Zephyr 的 st7789v 驱动初始化**不发 `DISPON(0x29)`**，
  面板停在 sleep-in 全黑；应用必须调 `display_blanking_off()` 点亮（裸机 init 末尾带 0x29）。
- **软复位延时不足**：无硬件 RST 的板子走 `SWRESET` 后若只延 5ms（ST7789 需 ~120ms），
  会出现间歇性初始化失败，须在驱动里补足到 ~120ms（注意上游驱动被覆盖后要重打补丁）。
- 跨 GUI 库复用同一屏幕驱动时，只需替换上层绘制，SPI 刷写路径可保持一致。

## 3. emWin (STemWin) GUI 栈

- **预编译静态库不能塞进 `add_executable` 源列表**（CMake 会静默丢弃 `.a`）：
  改用 `add_library(... STATIC IMPORTED)` + `target_link_libraries` 配合
  `-Wl,--start-group/-Wl,--end-group` 处理循环引用。工具链 binutils 版本需满足预编译库要求。
- **`GUI_Init()` 死循环根因**：STemWin 入口用硬件 **CRC 外设**做完整性校验，
  未使能 CRC 时钟则校验永远失败 → 死循环。在 `GUI_Init()` 之前使能 CRC 时钟
  （CRC 在 AHB4，`RCC->AHB4ENR` 的 `CRCEN`）。
- **颜色字节序相反**：`GUI_USE_ARGB=0` 时 `GUI_COLOR` 是 `0x00BBGGRR`（蓝在高字节），
  LVGL 是 `0x00RRGGBB`。传给 `GUI_SetColor()` 前做一次 R/B 交换才能与像素一致。
- 显示管线：`GUI_DispString*` → 本地 VRAM(RGB565) → 拷贝缓冲刷 ST7789。
- 中文字体沿用 GBK 点阵方案（见 `storage-and-filesystems.md`）。
- 验收要求：Debug 构型给出 FLASH/RAM 占比用于版本对比，且**双构零警告**。

## 4. F429 LCD 8080 总线（800×480 类屏，NT35510 / ILI9806E）

- FMC Bank1 NE1 8080 16-bit；`RS` 接某地址线，`LCD_BASE = 0x60000000 | addr_offset`。
- **`lcd_scan_dir` 的宽高交换逻辑是模块厂原版且正确，不可改反或删除**：
  `DFT_SCAN_DIR=L2R_U2D`(MV=0) 下因 `lcd_width(800) > lcd_height(480)` 触发交换 →
  有效 GRAM 窗口为 **480×800**（控制器铺满物理屏所需窗口）。
  屏幕物理尺寸只由 `LCD_WIDTH/LCD_HEIGHT` 决定。
- 因此 **LVGL 画布尺寸 = GRAM 窗口 = 480×800**（不是 800×480）；
  布局一律从 `lv_disp_get_hor_res/ver_res()` 自适应取，硬编码会渲染错位。
- **地址窗口必须按 MIPI-DCS 时序写**：命令写一次 + 跟 4 个数据字节。
  把 `0x2A/0x2B/0x2C` 当连续寄存器逐个拆写会写错 GRAM，表现为文字重叠。

## 5. 电容触摸 GT911/GT9147（软件位绑定 I2C）

- 芯片只有 I2C 模式（无 SPI），可走软件位绑定 I2C：排针 `T_SCK=CT_SCL`、`T_MOSI=CT_SDA`、
  `T_CS=CT_RST`、`T_PEN=CT_INT`。GT911 自报 product ID "911"、地址 `0x14`，
  报点分辨率应与画布一致。
- **184B 配置块是 GT9147 专用，绝不能给 GT911 上传**；GT911 用恒等映射即可。
- **中断只当唤醒，任务必须轮询到抬手**：INT 行为因模组而异（单次/持续脉冲），
  任务随后按固定周期轮询直到连续多次无触点。
- 无需手指即可验证 EXTI 链路：调试器 `halt` → 直接写 `EXTI_SWIER` 对应位 → `resume`，
  产生与引脚边沿等价的中断。

### 5.1 中断风暴三层防护（真机教训）

症状：`T_PEN` 配成浮空输入且紧邻位绑定 I2C 的 SCL 线 → 串扰耦合出边沿，
实测可达数万次/秒；ISR 抢占低优先级的轮询式 I2C 传输 → HAL 超时 → 从机拉住 SDA →
I2C 总线 BUSY 锁死。三层防护缺一不可：

| 层 | 措施 |
|---|---|
| 源头 | `T_PEN` 改 `GPIO_PULLUP`（仅地址锁存一瞬用 NOPULL）；位绑定 I2C 事务期间屏蔽 EXTI line |
| 隔离 | 传感器读取用 `vTaskSuspendAll()/xTaskResumeAll()` 包成原子操作（中断仍开）；ISR 内**立即屏蔽该 line**，任务侧消抖后重新武装 |
| 容错 | I2C 超时放大；失败先恢复总线再立即重试一次；轮询上限兜底 |

**正解是"ISR 内自屏蔽 + 任务侧延时重武装"，不是在 ISR 里做软件滤波**：
噪声中断的解法是切断噪声源（上拉）并阻止噪声进 ISR，而非滤波。
另给所有外部中断加 **1s 窗口速率看门狗**（超阈值打 WARNING），把"风暴"变成日志里的数字，
是这类问题最划算的诊断投入。

```c
/* ISR 入口：立刻屏蔽本 line，避免噪声继续进中断 */
EXTI->IMR &= ~TOUCH_EXTI_LINE_MSK;
xSemaphoreGiveFromISR(s_touch_sem, &hp);

/* 任务侧：轮询到抬手 + 去抖之后重新武装 */
void bsp_touch_irq_rearm(void)
{
    taskENTER_CRITICAL();
    EXTI->PR  =  TOUCH_EXTI_LINE_MSK;    /* 先清挂起，避免立即重触发 */
    EXTI->IMR |= TOUCH_EXTI_LINE_MSK;    /* 再重新武装 */
    taskEXIT_CRITICAL();
}
```
