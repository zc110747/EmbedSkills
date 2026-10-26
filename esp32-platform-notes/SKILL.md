---
name: esp32-platform-notes
description: ESP32（S3/C3/C6）：Arduino CLI 与 ESP-IDF 构建、RGB 面板位移失步、GT911 触摸无响应、SPI 模式 SD 挂载失败、Cortex-Debug 与组件链接陷阱。
agent_created: true
---

# ESP32 平台速查

Arduino CLI 与 ESP-IDF 两条构建链上的**知识、判据与反模式**。逐条配方、完整配置与报错对照表见 `references/`。

## 何时用
- 用 arduino-cli / ESP-IDF 构建固件，遇到构建模型、依赖、环境异常。
- 板载 WS2812 灯不亮、BOOT 键读不到、串口/烧录口识别不到。
- Cortex-Debug + openocd-esp32 断连，或报 `Arg list too long`、LIBUSB 错误。
- 链接期报回调 `undefined reference`，或 `__weak` 覆盖静默失效。
- WiFi 站连不上、开机不自动重连、重试次数与实际尝试对不上、或担心 WiFi 吃掉内部 SRAM 影响显示。

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
| RGB 面板位移 | 整幅图**固定位移且右缘绕回左边** = DMA 带宽不足导致扫描失步（permanent desync），**不是 porch**；解法 = **只用 bounce buffer**，`CONFIG_LCD_RGB_RESTART_IN_VSYNC` 要**关掉**（见下行） |
| bounce buffer 的代价 | 反弹填充是**GDMA EOF 中断里的 CPU `memcpy`**（`esp_lcd_panel_rgb.c:1042`），每帧整帧一遍（768000 B / 16000 = 48 块 × 39 fps ≈ 30 MB/s 全在 ISR）。它**正是让 VSYNC 中断变晚的原因** |
| `RESTART_IN_VSYNC` 反噬 | 打开它 = 每个 VBlank **无条件**重启 GDMA（`:1276` `do_restart = true`），且**编译掉**驱动自己的精确欠载检测 `bb_eof_count < expect_eof_count`；驱动注释（`:1265`）承认无条件重启**自己**会造成单帧位移。与 bounce 同开 = 制造自己要防的条件 |
| 显示通路 CPU 占比 | FreeRTOS 运行时长统计**不把 ISR 时间归给任何任务** → `vTaskList`/`%CPU` 里 taskLVGL 很低**不等于**显示通路不忙。先查驱动里有没有 ISR 内的大块 `memcpy` |
| direct 模式的 flush 阻塞 | `esp_lvgl_port_disp.c:748-756` 在 `direct_mode/full_refresh` 下**无条件** `xSemaphoreTake(trans_sem, portMAX_DELAY)` 等**一整帧** → 改两个像素也要等满一帧；输入轮询在同一任务同一 `lv_timer_handler()` 里，落在 flush 期间的触摸要等它出来 |
| 刷新率 vs 面板 | `LV_DEF_REFR_PERIOD` 一个值管**三件事**（显示刷新 / 输入设备读取 / 动画步进），是**请求不是上限**。面板只有 39 Hz 时它按 62.5 Hz 要帧，日志里别把它当帧率读 |
| esp_lvgl_port RGB | `flags.bb_mode` 必须与 `bounce_buffer_size_px != 0` **成对**；`avoid_tearing` 把面板自身 FB 直接当 LVGL draw buffer，硬前提 `num_fbs==2` + 64B cache line |
| GT911 触摸无响应 | I²C 能读到 `TouchPad_ID` / `Config_Version`，却**永远读不到触摸点** → 先查主机侧有没有给 INT 上拉。GT911 的 INT 是**开漏输出**，无上拉时空闲电平悬空。复位按官方 `waveshare_rgb_lcd_port.c`：RST 低 **100 ms** → INT 拉低 → **100 ms** → RST 高 → **200 ms**（10 ms 是数据手册的*脉冲*最小值，不是上电窗口） |
| esp_lvgl_port 输入节拍 | 主循环**只在 `LVGL_PORT_EVENT_TOUCH` 事件时**才主动 `lv_indev_read()`（该事件只由触摸中断回调置位）；但 TIMER 模式的 indev 仍有 LVGL 自带 read_timer（`lv_indev.c:133`；`lv_indev_set_mode` **只在 EVENT 时 pause**），`lv_timer_handler()` 会跑到它 → **不配 IRQ 的轮询路径同样成立**，别急着改成中断 |
| 配置生成 | `sdkconfig.defaults` 只在 `sdkconfig` **不存在**时参与生成；改完 defaults 不删 sdkconfig = 构建全绿而行为不变 |
| SPI-SD 挂载失败 | CS 由**扩展器**驱动的板子，必须在 mount 前做"**CS 高 + ≥74 个 400 kHz 空闲时钟**"。缺它 → 卡片粘在半条命令上，而**芯片复位不切断卡片供电** → 复位/重烧都救不回，症状伪装成"卡坏了"。`0x102`/`0x107` 且复位无效时先补唤醒序列 + 重试，不要先换卡。详见 `references/spi-sd-bringup.md` |
| SDIO 探测 ≠ 故障 | `CONFIG_SD_ENABLE_SDIO_SUPPORT=y` 时 **SPI 模式也会先发 CMD52/CMD5**，普通 SD 卡必然回 "command not supported"，**无害**。且默认 `LOG_MAXIMUM_LEVEL=INFO` 只看得见这两条（它们走 `ESP_LOGI`），R1 路径走 `ESP_LOGD` 被整段编译掉 → 命令序列是盲区，别据此判"驱动走错分支" |
| WiFi 主动断开 ≠ 故障 | `WIFI_REASON_ASSOC_LEAVE`(8) / `STA_LEAVING`(36) **只可能**由本机 `esp_wifi_disconnect()` 产生。切 SSID 前重配、扫描前让出射频这两处**在意图仍是"想要链路"时断开**，只判意图标志会把它们记成失败 → 日志出现 `attempt 2/3` 而没有 `1/3`。**意图标志回答"要不要链路"，reason 回答"是不是故障"，必须分开判** |
| `esp_timer_start_once` 反噬 | 对**已武装**的定时器再次调用返回 `ESP_ERR_INVALID_STATE` 且**不重启**（原到期时间不变）。一个重试窗口内两次故障 → 第二次武装静默无效，白吃一格预算。症状是两次故障间隔**远小于**设定延迟。修：先 `esp_timer_stop()` 再装，或用 `pending` 标志合并同窗口重复报告 |
| `WIFI_STORAGE_RAM` 的代价 | 想让凭据只有一个主人（`WIFI_STORAGE_RAM` + `CONFIG_ESP_WIFI_NVS_ENABLED=n`，日志打印 `config NVS flash: disabled`）时，**配置不跨复位** → **每次关联含开机都必须先 `esp_wifi_set_config()`**。漏掉是静默的：`esp_wifi_connect()` 返回 `ESP_ERR_WIFI_SSID`、**不产生任何事件**、返回值常被丢弃 → 状态机永远停在 connecting 且无 handler 会纠正。实测正确路径 1.2 s 进 auth，漏掉则完全没有 auth 行 |
| 扫描 vs 关联 | 关联中扫描**两种行为都真实存在**：有时返回 `ESP_ERR_WIFI_STATE`，有时"成功返回但关联静默死掉"→ 不能按返回值判断。正解：扫描前主动 `esp_wifi_disconnect()` 让出射频（状态**留在 connecting**，这是暂停不是取消），扫描结束后重新 `esp_wifi_connect()`；**扫描启动失败的分支也必须恢复关联**，否则永远停在暂停态 |
| WiFi 与 RGB 面板 | 站会从**内部 SRAM** 拿走约 75 KB 量级，而那是 bounce buffer / DMA 描述符所在的池子。`CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP=y` 把流量缓冲推去 PSRAM；**关键是顺序**：`display_init()` 必须早于 `net_init()`。把它提前不只是改启动顺序，而是改面板的**内存保证** |

## 判据与反模式

- **两个修复同时上 = 无法归因。** 位移/闪烁这类"改了 A 也改了 B 然后好了"的场景，事后必须做一次**单变量回退**确认哪一个是必需的、哪一个只是搭便车甚至反噬。本项目就是靠回退才发现 `RESTART_IN_VSYNC` 在与 bounce buffer 打架。
- **官方 Kconfig help 只说好处，副作用写在代码注释里。** 判断一个开关值不值得开，必须读它 `#if` 分支里的代码**和**旁边的注释，不能只读 Kconfig 的 help 文字。
- **"某个子系统不动"要分层取证，不要按猜测改配置。** 触摸这类链路至少三层：硬件（引脚电平）/ 驱动（`touch->data.points`）/ 框架（indev 事件计数）。**三层同时被动观测，一次烧录即可定位**，胜过猜一版烧一版。被动 = 只读已有变量加一个引脚电平，不碰总线。
- 反模式：写一个"直接读触摸状态寄存器"的探针来诊断触摸。GT911 的 `0x814E` 是 **buffer-ready + 读后写 0 清除** 协议，探针每采一次就**抢走一次驱动的事件位** —— 诊断本身变成故障源。
- 反模式：只看官方例程的 `.c` 就断定"官方配了中断"。要拿到 `.h`：`EXAMPLE_PIN_NUM_TOUCH_INT = (-1)` 才证明官方也走轮询。
- 反模式：把"**复位救不回来的 SD 挂载失败**"当成硬件故障去换卡换线。**芯片复位不切断 SD 卡供电**，卡片状态粘住时只有整机断电、或"CS 高 + ≥74 空闲时钟"能清 —— 后者才是固件必须自愈的路径，不能指望用户拔电源。
- 反模式：把诊断探针留在交付固件里。探针在启动序列里崩溃 = 用户看到的"设备自己在反复重启"，还会把它正要测量的硬件（比如那张粘住的卡）拖进坏状态：**诊断本身变成故障源**。
- **探针在场时的绿灯不可信 —— 移出后必须重抓一次日志。** 探针往往自己走**完整**路径，顺手把被测代码该做而没做的前置动作做了（实测：带探针时开机自连"正常"，移出探针后同一固件开机永不自连，因为探针自己调了 `set_config`）。否则你验收的是"探针 + 固件"，而探针不在交付物里。与上一条互补：上一条防探针自己成为故障源，这条防探针**掩盖**别人的故障。
- **重试类逻辑的账目必须能对账。** 计数器说重试 N 次，日志里就该有 N 条 `attempt`，编号 `1..N` **无缺口**，且每条与它前面最近一次失败的时间差 **≥** 设定延迟。三条里任一条不成立都指向"有非故障事件被计入了"或"定时器没重启"。把这三条写成脚本断言——它们都是纯日志可判的，不靠猜。
- 反模式：在验收脚本里**写死**重试次数/延迟等常量。常量一改脚本跟着"通过"，验证变成自证。要从源码正则读出来再断言。
- 反模式：脚本在读不到任何输入时返回成功（`0/0 checks passed` 会被打印成通过）。**假绿比没有脚本更糟**：没有任何输入时必须显式失败并提示怎么喂数据。
- **意图与故障要分开判，别合成一个条件。** "用户想要什么"（意图标志）与"这份报告是不是故障"（事件 reason）是两个正交问题；合成一个判断，就一定会有一类调用点落在错误分支上 —— WiFi 的重试账目错位就是这么来的。
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
- `references/rgb-lcd-panel.md`：RGB/DPI 面板位移与失步的症状-根因对照表、可检索原文、bounce buffer 配方**及其 ISR 内 memcpy 的真实代价**、`RESTART_IN_VSYNC` 的反噬（无条件重启 + 编译掉欠载检测）、"两个修复同时上=无法归因"的方法论、direct 模式 flush 阻塞一整帧与卡顿定性、IRAM 回调约束、esp_lvgl_port 配对约束、带宽预算与标尺取证法。
- `references/gt911-touch.md`：GT911 触摸无响应的症状-根因对照表、官方例程配置逐条真值（含 `EXAMPLE_PIN_NUM_TOUCH_INT = -1` 这个"官方也走轮询"的关键证据）、复位时序与 INT 开漏/上拉语义、esp_lvgl_port 的 TIMER/EVENT 两条输入路径对比、三层被动取证配方与判据、可直接照抄的探针代码骨架。
- `references/spi-sd-bringup.md`：CS 挂在扩展器上的 SPI-SD bring-up —— 为何 mount 前必须"CS 高 + ≥74 个 400 kHz 空闲时钟"（可直接照抄的临时无 CS 设备发时钟代码）、"复位救不回来"的物理原因（芯片复位不切断卡片供电）、只看得见 CMD52/CMD5 是因为 R1 路径走 `ESP_LOGD` 被编译掉的取证配方、SDIO 探测的正确解读与 `0x102`/`0x107` 对照、失败重试为何安全。
- `references/wifi-station.md`：ESP-IDF WiFi 站的**静默故障**三件套与可断言判据 —— reason 8/36 为何必须与意图标志分开判（重试账目错位：`attempt 2/3` 而没有 `1/3`）、`esp_timer_start_once` 对已武装定时器静默无效的两种修法与"重试节拍 ≥ 延迟"这条唯一能抓住它的断言、`WIFI_STORAGE_RAM`+驱动 NVS 关闭时配置不跨复位导致开机不自连（`ESP_ERR_WIFI_SSID` 不产生事件）、**探针掩盖故障**的方法论、WiFi 吃掉内部 SRAM 与"面板的记忆保证 = 分配顺序"、扫描/关联互斥的两种真实行为与恢复点，以及一份可直接脚本化的验收清单（含两条脚本纪律：常量从源码读、读不到输入必须失败）。
