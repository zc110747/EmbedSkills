# 显示点亮、GBK 字库与 LVGL 集成

## 1. ST7789 默认全黑的两层原因

### 1.1 驱动初始化不发 DISPON(0x29)

Zephyr 的 st7789v 驱动初始化结束时面板仍处于 sleep-in，全黑且无任何报错。应用侧必须显式点亮：

```c
display_blanking_off(display_dev);
```

### 1.2 软件复位延时不足

面板无硬件 RST 时驱动走 SWRESET，其后延时只有毫秒级，而 ST7789 复位约需 120 ms。
延时不足会让后续初始化命令（含 SLPOUT）被忽略 → 仍然全黑。修法是 patch
`display_st7789v.c`，在 SWRESET 后加长延时：

```c
k_sleep(K_MSEC(120));
```

⚠️ patch 位于 zephyr 模块目录内，`west update` / 重装模块后会丢失，需重新应用（或用
fork / 补丁队列固化）。

## 2. SD 卡 GBK 点阵字库

### 2.1 文件布局

字库放 SD 卡约定目录，分两类：

- 索引文件（如 `UNIGBK.BIN`）：Unicode ↔ GBK 映射。
- 点阵文件（如 `GBK12.FON` / `GBK16.FON` / `GBK24.FON` / `GBK32.FON`）：按字号分开。

点阵格式为 **MSB 优先、列扫描**，不是 LVGL 需要的行优先。

### 2.2 索引文件的双段结构（核心坑）

- 段 1（前约 21792 条）：`[uni_lo, uni_hi, gbk_lo, gbk_hi]`，按 Unicode 升序。
- 一条全 0 记录作为分隔。
- 段 2（其余）：`[gbk_lo, gbk_hi, uni_lo, uni_hi]`，按 GBK 升序。

所以**不能整体二分**。正确做法：初始化时顺序扫描定位第一条全 0 记录拿到段 1 边界，
之后只在段 1 内二分。

另外文件里的 GBK 字段是小端存储，取出时必须**交换字节序**，否则汉字整体错位
（典型症状：显示成字形相近但完全不同的字）。

### 2.3 Unicode → GBK → 转置 的桥接流程

1. LVGL 解码 UTF-8 → Unicode。
2. 在索引文件段 1 内二分查到 GBK（注意小端交换）。
3. 按 GBK 算点阵偏移 `190 * (qh - 0x81) + (ql - 0x40 或 0x41)`，取出原始点阵。
4. 把列扫描 / MSB 优先的点阵**转置**成 LVGL 的 1bpp 行优先位图。
5. ASCII 用自带点阵字模回退（避免 Montserrat 小字号在点阵屏上发虚）。

每个字号绑定一个 `lv_font_t`，UI 直接引用。

### 2.4 缺字处理

字库文件缺失或卡未挂载时，中文行会静默回退成空白。UI 必须显式提示"字库未加载"之类状态，
否则会被误判为渲染 bug。

## 3. LVGL 集成

- **内存池**：Zephyr LVGL 模块默认 `LV_Z_MEM_POOL_SIZE` 仅 2 KB，创建几个 label/timer 就会
  野指针、总线错误。调到 64 KB（`65536`）。
- **tick 来源**：Zephyr 的 `lv_conf.h` 启用 `LV_TICK_CUSTOM`，时间由 `k_uptime_get_32()` 提供；
  应用线程只需周期调 `lv_timer_handler()`，**不要**（也无法）调 `lv_tick_inc()`。

## 4. Zephyr shell 控制台

`CONFIG_SHELL=y` + dts 里 `zephyr,shell-uart`。命令用 `SHELL_CMD_REGISTER` 注册，整个文件可
拷到任意 Zephyr 工程复用。有用的自检命令：

| 命令 | 用途 |
|---|---|
| 版本/系统信息 | Zephyr、LVGL 版本，运行时间，主频，主栈用量 |
| 字库状态 | 索引文件与各字号点阵是否加载 |
| LVGL 堆统计 | total / free / biggest / used% / frag% |
| `kernel uptime` / `kernel threads` | 运行时间 / 线程列表 |
| `device` | 设备树设备列表（确认 overlay 生效） |

提示符用 `shell_prompt_change()` 修改，需 `CONFIG_SHELL_PROMPT_CHANGE=y`。

## 5. 下载与调试（Cortex-Debug）

`launch.json` + `tasks.json`：F5 先跑 `python -m west build`，再启动 OpenOCD。

- `serverpath` 指向 `openocd.exe`，`searchDir` 指向 scripts 目录，`configFiles` 指向自备
  `openocd.cfg`（SWD + adapter speed）。
- `device` 填芯片型号，`rtos` 填 `Zephyr`。
- 另接一个小脚本（如 Python 串口抓取）可一键复位目标并抓启动日志。
