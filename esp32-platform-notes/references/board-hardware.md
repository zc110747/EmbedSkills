# ESP32-S3 板级硬件与真机验证

适用：ESP32-S3（OPI PSRAM + 16 MB Flash 模组）+ Arduino Core 3.3.x。端口/路径以占位符表示。

## 1. 板级硬件事实（典型 DevKit 级设计）

| 元件 | 连接 | 软件可控 |
|---|---|---|
| 用户 LED | **WS2812B RGB，数据线 GPIO48**（单线 800kHz，GRB 字节序） | 是（须专用驱动） |
| BOOT 按键 | GPIO0，10k 上拉到 VDD33，active-low | 是 |
| 电源灯 | +5V → 限流电阻 → LED → GND（电源常亮） | 否 |
| TX 灯 | U0TXD(GPIO43) → 限流电阻 → LED → GND（UART TX 活动） | 否 |
| RX 灯 | U0RXD(GPIO44) → 限流电阻 → LED → GND（UART RX 活动） | 否 |

常见误区：不少资料把 ESP32-S3 的用户 LED 说成 GPIO2 普通数字脚，或认为 GPIO48 只能当 WS2812 别当数字脚。实际上 GPIO48 **确实接了 WS2812B 真彩灯**，但走单线协议，不能用 `digitalWrite`；GPIO2 通常只接自动下载上拉电阻、没有用户灯。

## 2. WS2812B 驱动方案

**禁止用 `digitalWrite` / `pinMode(OUTPUT)` 直接驱动**：WS2812B 是严格 800kHz 单线时序（每 bit 高低电平宽度约 0.4µs / 0.8µs），FreeRTOS 多任务加中断下 bit-bang 极不可靠。

标准做法：Adafruit_NeoPixel（内部走 ESP32 RMT 外设，cycle-accurate）。

- 安装：`arduino-cli lib install "Adafruit NeoPixel"`
- 构造：`Adafruit_NeoPixel s(1, 48, NEO_GRB + NEO_KHZ800);`（1 像素、GPIO48、GRB、800kHz）
- 点灯：`begin()` → `setBrightness(40)` → `setPixelColor(0, Color(r,g,b))` → `show()`
- 熄灭：`setPixelColor(0, 0,0,0)` → `show()`

### 工程化封装范式

- 配置头用 `LED_IS_WS2812` 宏切换两套驱动：
  - `=1`：WS2812 路径，含 `LED_PIN`、`LED_WS2812_BRIGHTNESS`、`LED_ON_*`（GRB 颜色）
  - `=0`：普通数字 GPIO LED 路径（`LED_ACTIVE_HIGH`）
- 对外只暴露 `led_set(bool on)`：`on` 映射固定 GRB 颜色，`off` 映射黑色。这样心跳翻转、按键翻转、UART `led on/off/toggle` 全部无需改动，自动作用于 RGB 灯。

## 3. 识别烧录/调试口

Windows 上 `Get-WmiObject Win32_SerialPort` 与 `.NET SerialPort.GetPortNames()` **都返回空**，会漏掉 USB 串口。唯一可靠方式是 pyserial 枚举：

```python
import serial.tools.list_ports as lp
for p in lp.comports():
    print(p.device, p.description, p.hwid)
```

- 板载 USB-Serial-JTAG：**USB VID:PID = 303A:1001**，既是**烧录口**（esptool / arduino-cli upload）也是**调试口**（openocd）。
- 端口号每次插拔/重启都可能变，**必须动态识别，不得硬编码**。
- 其余端口忽略：主板串口、FTDI（ESP-Prog）、CH343 等。CH343 类 USB-UART 桥只能下载，不能调试。

## 4. 编译（先确保 elf 最新）

```bash
arduino-cli compile -j 8 \
  -b esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M,PartitionScheme=default,UploadSpeed=921600 \
  --build-path .build .
```

验收：**0 error / 0 warning**，生成 `.build/<proj>.ino.elf`。

## 5. 烧录

烧录脚本（纯下载、不编译，需先有 `.build`）注意点：

- **必须用原生 PowerShell 跑批处理**（Git Bash 跑 .bat 不可信、常无输出误判）：

  ```powershell
  & ".\flash.bat" <PORT> --no-pause 2>&1 | Out-File -FilePath flash_run.log -Encoding utf8
  ```

- 让脚本把 esptool upload 输出单独落一个日志文件，整体 stdout 再落另一个，便于对照。
- 成功标志：脚本自打印 `[FLASH] PASS` + `[RESET] PASS` + esptool `Hash of data verified.`。
- 脚本应内置 pyserial 列举端口（无参运行则扫描并提示选择），也支持显式传入端口。

## 6. 串口验证（功能验收）

烧录与串口监控共用同一板载口，**115200 8N1**。用 pyserial 读若干秒确认运行：

```python
import serial, time
s = serial.Serial("<PORT>", 115200, timeout=1)
time.sleep(3)                      # 等启动横幅
print(s.read(2000).decode(errors="replace"))   # 启动横幅 + 任务列表 + 心跳
for cmd in ("led on\r\n", "led off\r\n", "led toggle\r\n"):
    s.write(cmd.encode()); time.sleep(2); print(s.read(500).decode(errors="replace"))
```

验收点：

- 启动横幅打印芯片/PSRAM/FreeRTOS/任务列表 → 固件正常启动
- UART 回显各命令的确认文本 → 控制命令链路通
- 肉眼确认板载 RGB 灯按命令亮/灭/翻转 → 驱动 + 硬件正常

## 7. 端到端验收清单

- [ ] 编译：0 error / 0 warning，elf 生成
- [ ] 端口：pyserial 识别到 Espressif USB-Serial-JTAG（动态识别，勿硬编码）
- [ ] 烧录：`[FLASH] PASS` + `Hash of data verified.` + `[RESET] PASS`
- [ ] 串口：启动横幅与任务列表可见，UART 命令回显正常
- [ ] 硬件：板载 WS2812B 亮灭与命令一致
