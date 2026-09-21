---
name: esp32-platform-notes
description: ESP32（S3/C3/C6）的 Arduino CLI / ESP-IDF 工程构建、板级硬件、Cortex-Debug 调试与组件链接陷阱速查。适用于"arduino-cli 编译 ESP32""WS2812 怎么驱动""openocd 报 Arg list too long"等请求。
agent_created: true
---

# ESP32 平台速查

Arduino CLI 与 ESP-IDF 两条构建链上的**知识、判据与反模式**。逐条配方、完整配置与报错对照表见 `references/`。

## 何时用
- 用 arduino-cli / ESP-IDF 构建固件，遇到构建模型、依赖、环境异常。
- 板载 WS2812 灯不亮、BOOT 键读不到、串口/烧录口识别不到。
- Cortex-Debug + openocd-esp32 断连，或报 `Arg list too long`、LIBUSB 错误。
- 链接期报回调 `undefined reference`，或 `__weak` 覆盖静默失效。

## 核心知识点

| 主题 | 要点 |
|---|---|
| Arduino 构建模型 | 根 `.ino` 与目录同名；子目录 `.cpp` **不被编译**，须在 `.ino` 内 `#include "x.cpp"` 拼成单一编译单元 |
| 头文件 | 用 `#ifndef/#define/#endif` 守卫（`#pragma once` 在多路径解析下失效）；每个 `.h` 自带其全部 include |
| 符号隔离 | 单一编译单元无 TU 隔离，符号须落在命名空间/类作用域内，否则跨模块串味 |
| 增量编译 | 保留 `--build-path` 即增量；arduino-cli ≥1.5 已移除 `--build-cache-path` |
| Core 3.3.x 变更 | `ledcSetup`/`ledcAttachPin` → `ledcAttach(pin,freq,res)`；`ledcWrite` 按 **pin** 而非 channel |
| 启动早期读 MAC | WiFi 驱动起来前 `WiFi.macAddress()` 返回全 0，须用 `esp_read_mac()` 读 eFuse |
| 板载灯 | WS2812B 是 800kHz 单线 GRB 协议，**禁用 `digitalWrite`**，走 RMT 驱动 |
| 串口识别 | `Win32_SerialPort` / `SerialPort.GetPortNames()` 会漏 USB 串口，唯一可靠方式为 pyserial 枚举 |
| 调试口 | 内置 USB-Serial-JTAG 既是烧录口也是 JTAG 调试口；普通 USB-UART 桥只能下载、不能调试 |
| JTAG 驱动 | Windows 默认把该口绑到 usbser，libusb 打不开，须用官方安装器装 WinUSB 驱动 |
| Cortex-Debug 字段 | `overrideLaunchCommands: []`、`serverArgs: ["-d2"]`、`runToEntryPoint: "app_init"`、**不写 `rtos`** |
| 组件链接 | ESP-IDF 组件是 `.a`，未被直接引用的目标文件（回调、`__weak` 覆盖）会被丢弃，须 `--whole-archive` 包裹 |

## 判据与反模式

- **口对了才谈调试。** JTAG 驱动装好后，命令行执行 `openocd -f board/<chip>-builtin.cfg -c "init; reset halt; shutdown"` 应打印 `Device found` + `Examination succeed` 且退出码 0。
- **报错看对窗口。** gdb-server 崩溃原因只在 **TERMINAL** 标签页可见，DEBUG CONSOLE 看不到。
- **符号强弱可验。** 链接后用 `nm -C <elf>` 核对回调为 `T`（强定义已链接），而非缺失或被 `W`（弱桩）取代。
- **端口必动态识别。** 串口号随插拔变化，硬编码端口即缺陷；唯一命中直接烧录，多命中/零命中才回退交互选择。
- 反模式：用 `#pragma once` 当守卫，或让 `.h` 依赖间接包含。
- 反模式：用 dummy 引用手工拉起目标文件绕开归档丢弃——脆弱；正解是 whole-archive。
- 反模式：用 Zadig 或旧 `idf-env driver install` 手装 JTAG 驱动，易把 CDC 接口误装成 WinUSB。
- 反模式：构建脚本清空 build 目录，丢掉增量收益。
- 反模式：建目录前不查忽略规则。`git add` **静默跳过**被忽略路径，先跑 `git check-ignore -v <新目录>/probe.txt` 探针；忽略规则大小写不敏感时 `debug/` 会被 `Debug/` 规则连坐。
- 反模式：静默等待长命令。构建/烧录超出正常时长后主动上报已运行时长与增量/全量状态并征询是否终止，终止后保留构建目录以便续编。

## 详细资料
- `references/arduino-cli-build.md`：构建范式与代码骨架、FQBN/依赖/增量、core 3.3.x API 对照、编译错误速修表、批处理与端口扫描配方、忽略规则事故复盘。
- `references/board-hardware.md`：板级元件表与可控性、WS2812 驱动与封装范式、烧录与串口验收流程。
- `references/cortex-debug.md`：工具链路径布局、完整 launch.json、15 类报错根因对照、排错顺序。
- `references/link-traps.md`：whole-archive 修复与 CMake 片段、验证方法、Git Bash 下 ESP-IDF 环境陷阱。
