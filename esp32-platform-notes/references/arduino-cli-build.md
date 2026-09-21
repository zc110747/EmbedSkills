# Arduino CLI 构建 ESP32：配方与踩坑

适用：ESP32（S3/C3/C6）用 arduino-cli + VS Code 构建模块化 C++ 工程。本文只涉及**平台级**事实，路径与端口一律以占位符表示，落地时按本机实测替换。

## 1. 构建模型（与 CMake 完全不同）

| 规则 | 说明 | 违反后果 |
|---|---|---|
| 根 `.ino` 必须与工程目录同名 | `<proj>/<proj>.ino` | `main file missing from sketch` |
| 子目录 `.cpp` 不会被自动编译 | 在 `.ino` 内统一 `#include "x.cpp"` 拼成**单一编译单元** | 链接期 `undefined reference` |
| 头文件用 `#ifndef/#define/#endif` | 构建器把工程复制到 `.build/sketch/` 用另一套路径解析，`#pragma once` 失效 | `redefinition of class/enum` |
| 每个 `.h` 自带其全部 include | 单一编译单元下 include 顺序敏感，间接包含必翻车 | `'xxx' was not declared` |
| 符号加命名空间/类作用域 | 无 TU 隔离 | 静态变量跨模块串味 |

### 1.1 单一编译单元骨架

```cpp
#include "app/gateway.h"
#include "app/event_bus.cpp"
#include "app/pin_manager.cpp"
#include "network/wifi_manager.cpp"
// ... 其余模块 .cpp
void setup() { /* 启动 */ }
void loop() { delay(1000); }
```

头文件照常 `#include "x.h"`；`.cpp` 用 `#include "x.cpp"`。

### 1.2 守卫宏写法

```cpp
#ifndef NETWORK_WIFI_MANAGER_H_
#define NETWORK_WIFI_MANAGER_H_
// ...
#endif // NETWORK_WIFI_MANAGER_H_
```

守卫宏 = 相对路径大写 + 下划线。

### 1.3 ELF 产物名

`VS Code launch.json` 的 `executable` 指向 `.build/<DirName>.ino.elf`；产物还包括 `.bin` / `.merged.bin` / `partitions.bin` / `bootloader.bin`。

## 2. 命令、FQBN 与增量

```
esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M,PartitionScheme=default,UploadSpeed=921600
```

```bash
arduino-cli compile -j 8 -b "<FQBN>" --build-path ".build" .
arduino-cli upload  -b "<FQBN>" -p <PORT> --build-path ".build" .
```

- ESP32 Arduino Core 装于 `<arduino-cli data>/packages/esp32`；`arduino-cli config dump` 查 data 目录。
- **增量编译**：core/库缓存在 data 目录自动生效；只要保留 `--build-path` 不删，改动文件即增量（首次全量数分钟，增量十几秒）。
- arduino-cli ≥1.5 **已移除 `--build-cache-path`**（会警告并忽略，`config dump` 无等价键）；一键脚本内不要清空 build 目录，需要干净构建时才手动清。
- `arduino-cli` 不一定在 PATH：先 `where arduino-cli`，失败再逐个试候选安装目录，仍失败给明确提示并退出——不要静默返回。

## 3. 依赖

外部库（核心不自带，需 `arduino-cli lib install`）：

| 库 | 用途 |
|---|---|
| ArduinoJson | JSON 序列化 |
| PubSubClient | MQTT |
| WebSockets | WS 服务端/客户端 |
| Adafruit NeoPixel | WS2812 状态灯（RMT 驱动，勿用 `digitalWrite`） |

幂等安装（可放一键脚本首跑，装完 `arduino-cli lib list` 核对）：

```bash
arduino-cli lib install ArduinoJson PubSubClient WebSockets "Adafruit NeoPixel"
```

- 安装报 `Download failed: performing HEAD request: ... EOF` 属**偶发网络抖动**，逐个重试即可，不要整批放弃。
- **核心自带、勿当外部库安装**：WiFi / WebServer / Preferences / HardwareSerial / Wire / Update / FreeRTOS。
- PlatformIO 的 `.platformio` 可能被本机清理守护进程锁定，导致 `packages.lock` 权限失败或框架解包死循环（长时间无进展）；ESP32 工程统一走 arduino-cli 更稳。

## 4. core 3.3.x API 变更

| 旧 API（已移除） | 新 API |
|---|---|
| `ledcSetup(ch, freq, res)` | `ledcAttach(pin, freq, res)` |
| `ledcAttachPin(pin, ch)` | 同上（合并） |
| `ledcDetachPin(pin)` | `ledcDetach(pin)` |
| `ledcWrite(ch, duty)` | `ledcWrite(pin, duty)`（按引脚，不按通道） |

```cpp
ledcAttach(pin, freq_hz, res_bits);
ledcWrite(pin, duty);
ledcDetach(pin);
```

编译报 `'ledcSetup' was not declared in this scope` 即此因。

- `SERIAL_5N1 .. SERIAL_8O2` 宏定义在 `cores/esp32/HardwareSerial.h`（enum 值），**不在** `esp32-hal-uart.h`；直接传给 `HardwareSerial.begin(baud, config, rx, tx)`。
- 字面量 `0` 在多重载 API 下会歧义 → 显式强转：`ledcWrite(pin, (uint32_t)0)`、`strip.setPixelColor(0, (uint32_t)0)`。
- `analogSetPinAttenuation()` / `analogReadMilliVolts()` 在 core 3.3.x 可用（内部走 ADC1 回退路径）。
- **启动早期读 MAC 必须走 eFuse**：`WiFi.macAddress()` / `WiFi.softAPmacAddress()` 在 WiFi 驱动初始化前返回**全 0**（先 `WiFi.mode(WIFI_MODE_AP)` 再读仍全 0）。正确做法 `esp_read_mac(mac, ESP_MAC_WIFI_STA)`，需 `#include <esp_mac.h>`。器件 ID 与 SSID 尾部宜同源（取 MAC 末两字节，如设备 ID `<name>-XXXXABCD` → AP 名 `wifi-ABCD`）。症状：AP SSID 变成 `wifi-0000`、设备名全 0 → 一律先怀疑"驱动未起就读 MAC"。

## 5. 批处理脚本铁律（Windows）

- **纯 ASCII**（禁中文注释），LF 无 BOM，避免 GBK 控制台乱码。
- `cd /d "%~dp0"` 前先去掉尾随反斜杠。
- **for 块内禁止 `echo` 外部数据**：设备描述里的 `)` 会提前闭合 for 块 → 扫描逻辑静默崩掉。把行解析抽成 `:subroutine`，在**块外**用延迟展开打印。
- for 块内 `2>&1` 写成 `> nul 2>nul`。
- `echo` / `REM` 行清洗 `& ( ) | < >`。
- 失败即 `pause`（英文输出）。

```bat
@echo off
where arduino-cli >nul 2>nul || (echo arduino-cli not on PATH & pause & exit /b 1)
arduino-cli lib install ArduinoJson PubSubClient WebSockets
arduino-cli compile -j 8 -b "<FQBN>" --build-path ".build" "%~dp0."
```

### 5.1 后台超时提醒约定

后台 `arduino-cli compile` 超过 5 分钟时主动提醒用户仍在进行，并询问是否终止；提醒附已运行时长、增量/全量、可用终止手段。全量正常数分钟、增量 1~3 分钟，超时大概率是缓存重建。同理适用于烧录等长命令：**超时主动上报并询问，不静默死等**。

### 5.2 诊断姿势

- 不要用 Git Bash 的 `cmd //c x.bat` 跑批处理诊断（会进 cmd 交互模式，打印横幅后停在提示符）。
- 正确做法：原生 PowerShell 落文件再读
  `& .\x.bat --no-pause 2>&1 | Out-File -FilePath out.txt -Encoding utf8`
  （该环境下 PowerShell 的 stdout 不回显）。

## 6. 端口扫描配方

双击无反应几乎都是**停在 `set /p` 等手输端口**，且日志被 `> log 2>&1` 吞屏。修法：双击即全自动识别，日志先重定向再 `type log` 回显。

```
主检测：arduino-cli board list
  1. 按行首 ^COM[0-9] 过滤（配置多个板卡时会有缩进续行，首列为空/Serial）
  2. ESP 端口按 esp32:esp32 匹配（S3 的 FQBN 是 esp32:esp32:esp32_family，
     按 esp32s3 精确匹配永假）
  3. 设备描述含 "(" ")"（如 Serial Port (USB)）→ for 块内 echo 会提前闭合，
     必须抽 :scan_line / :py_line 子例程，列表在块外用 !VAR! 打印
兜底：pyserial 扫 comports()，按 Espressif VID 0x303A 匹配
  - 先 python -c "import serial" 预检：双击时 where python 可能命中
    应用商店存根，pyserial 会静默失效
选择策略：唯一命中 → 直接烧录；多个/零个命中 → 才回退 set /p 让用户选
烧录：arduino-cli upload -p %PORT% -b "%FQBN%" --build-path "%BUILD%"，事后 DTR/RTS 复位脉冲
```

## 7. 忽略规则事故复盘

事故形态：把硬件驱动放在 `debug/`，磁盘丢失后发现**从未被 git 跟踪**；最初误判为"漏了 `git add`"，真因是仓库根的忽略规则（为另一批工程写的）：

```gitignore
**/Drivers        # 与想要的分层名冲突
**/third_party    # 与想要的分层名冲突
**/zephyr
**/Debug/*        # 真凶：Windows 大小写不敏感，debug/ 被 Debug/ 连坐
**/Release/*
**/obj/*
**/.build
```

`git add` 会**静默跳过**被忽略文件，不报错不提示——"我明明 add 过了"是幻觉。

**铁律：建新目录前先跑探针**

```bash
git check-ignore -v <工程>/<新目录>/probe.txt
# 有输出 = 被屏蔽，换名；无输出 = 安全
```

已知黑名单（多工程仓库勿用）：`Drivers` / `third_party` / `zephyr` / `Debug`（含小写 `debug`）/ `Release` / `obj` / `.build`。
安全替代：硬件驱动用 `bsp/`，第三方库用 `lib/` 或 `vendor/`。

若已踩坑，重建依据优先级：**调用点（.ino 里怎么调的） > 文档里的 API 与协议契约 > 记忆**。因此文档中的 API 签名与 JSON 协议字段必须写精确——这是唯一可还原的凭据。

## 8. 常见编译错误 → 修复

| 报错 | 修复 |
|---|---|
| `constexpr IPAddress ... not literal` | 改 `const IPAddress`（IPAddress 非字面量类型） |
| `'JsonObjectConst'/'JsonDocument' does not name a type` | 缺 `#include <ArduinoJson.h>` |
| `'RESERVED_COUNT'/'RUN_LED' was not declared` | 头文件补 `#include "config/pin_config.h"` |
| `'WiFi' was not declared` | 头文件补 `#include <WiFi.h>` |
| `'ledcSetup' was not declared in this scope` | core 3.3.x 已移除，改 `ledcAttach` |
| 自由函数回调访问 `_self`/`onMessage`/`onText` 报 private | 把这些静态成员/回调方法移到 `public` |
| `Update.write` const 转换错误 | `const_cast<uint8_t*>(data)` |
| 私有方法被 `.cpp` 先调用报 not declared | 在 `.h` 补私有声明 |

## 9. 验收

- 一键脚本退出码 0，**零错误零警告**。
- 记录 arduino-cli 输出的 Flash/DRAM 占用与上限百分比（如 `FLASH xxxB / 16MB (xx%)`）。
- 真机功能验证（UART/ADC/GPIO/MQTT/WS/OTA）不阻塞编译交付，但应列入回归清单。

## 10. VS Code 任务

- `tasks.json`：`Build (arduino-cli)` 默认任务，等价第 2 节的 compile 命令。
- `launch.json`：Cortex-Debug 配置，`executable` 指向 `.build/<DirName>.ino.elf`；完整配置见 `cortex-debug.md`。
