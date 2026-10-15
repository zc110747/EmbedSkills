---
name: lvgl9-mcu-porting
description: LVGL v9.x 移植到裸机 MCU（RT-Thread/裸机+framebuffer）的高频陷阱与正解：v9 tick 回调、lv_color_hex RGB888、静态库 vs section 表、开机启动画面/动作条与多屏交接、短命启动帧 SWD 取证、file(GLOB) 不追踪新文件、SWD+串口验收。触发：LVGL 移植、v8 升 v9、首屏冻结、颜色不对、framebuffer 显示驱动、启动画面/开机动画、复位彩条、多屏切换。
---

# LVGL v9.x MCU 移植陷阱

## 1. v8 → v9 破坏性变化（实测踩坑）

- **`LV_TICK_CUSTOM` 宏已删除**：v9 的 lv_conf_internal.h 无此门控，写了就是死代码。
  症状：首屏渲染一次后**永久冻结**（动画/timer 全停，partial 模式 flush 数 = 整屏行带数）。
  **正解**：运行时注册 `lv_tick_set_cb(cb)`，`uint32_t cb(void)` 返回毫秒
  （RT-Thread 用 `rt_tick_get_millisecond()`，需 RT_TICK_PER_SECOND=1000）。
- **`lv_color_hex()` 收 RGB888（0xRRGGBB）**：传 RGB565 常量会渲染成完全不同的色相
  （0xF800 = RGB888 亮绿）。判定特征：帧内几何/行结构完全正确、色块内值恒定，
  但每个值都能用"888→565 重转换"逐位解释。像素断言用 0xFF0000/0x00FF00/0x0000FF/0xFFFFFF。
- `lv_theme_default_init(...)` 返回 `lv_theme_t*` 且已作用于 display，勿再 `lv_display_set_theme`。
- `lv_mem_monitor_t` 字段：`total_size/free_size/used_pct/max_used`（无 used_size）。
- anim exec 回调：控件 setter 多带第三参（如 `lv_bar_set_value(obj,v,anim)`），
  直接 cast 成 `lv_anim_exec_xcb_t` 会把垃圾传入第三参 → 包一层 `void cb(void*,int32_t)`。

## 2. 构建集成

- LVGL 无 RT-Thread 式 section 表注册（INIT_APP_EXPORT/MSH_CMD_EXPORT 那类依赖
  linker section 的**必须编译进最终镜像**，放 .a 会被静默 gc 成死控制台）；LVGL 纯
  API 调用 → **静态库安全**，未用控件/驱动按符号提取 + `--gc-sections` 裁剪。
- 上游源码零修改约定：静态库整体 `-w` 关警告，零警告铁律只约束自研代码。
- 重型库默认关闭：`LV_USE_VECTOR_GRAPHIC=0`（thorvg ~1.1MB 源不编译）、freetype/ffmpeg=0。
  裸机配置只需覆盖项（LV_COLOR_DEPTH 16、LV_USE_OS=LV_OS_NONE、LV_MEM_SIZE、
  主题/字体），其余走 lv_conf_internal 默认。
- lv_conf.h 放 lvgl/ 上层目录即可命中 `../../lv_conf.h` 相对包含。

## 3. framebuffer 移植要点（v9 display API）

```c
lv_init();
lv_tick_set_cb(tick_ms_cb);                       /* v9 必须 */
lv_display_t *d = lv_display_create(W, H);
lv_display_set_flush_cb(d, flush_cb);
lv_display_set_buffers(d, buf, NULL, BUF_BYTES, LV_DISPLAY_RENDER_MODE_PARTIAL);
```

- PARTIAL 模式行缓冲 40~50 行（800×40×2B=64KB 内部 SRAM 起步），flush 逐行 memcpy
  进 SDRAM fb；buffer 尺寸按**字节**给，格式默认 RGB565（LV_COLOR_DEPTH 16，swap=0）。
- flush_cb 的 area 是 display 绝对坐标；行距按 area 宽 tight 排列（无 stride）。
- 线程模型：单 LVGL 线程跑 `lv_timer_handler()`（返回下次调用 ms，cap 到刷新周期）；
  其他线程只置 volatile 标志/读 32 位计数，不碰对象。
- lv_conf 的 LV_MEM_SIZE 用 builtin tlsf 池（128KB 够常规 demo）；不用 LVGL OSAL
  （LV_USE_OS=LV_OS_NONE）时一切同步自管。

## 4. 验收模式（串口 + SWD 双通道）

- 活体判据：fps 计数（flush_cb 计数、1s 采样差值）> 20；两次 SWD 读 fb sum 不同。
- 确定性像素断言：专用 test 屏（无圆角/边框/阴影/滚条的纯色 rect，已知坐标），
  SWD 读 fb 断言色块中心 + 背景点精确等于期望 565 值。
- pyOCD 坑：**connect 后必须 t.reset()**，否则 RT-Thread shell RX 致聋（TX/心跳正常）；
  串口先开再 connect，reset 后从缓冲读 banner（勿先 reset_input_buffer）。
- Python 端低级坑：`"0x40".strip("0x")` 会把尾部 0 剥成 "4"，比对用 `s[2:]`。

## 5. 开机启动画面（boot splash）与多屏交接

驱动起来到主 UI 之间存在一段"framebuffer 里是占位内容"的窗口（有人直接
`fill()` 黑屏或画测试彩条）。正规做法是**启动动作条**，且**在 LVGL 线程内自驱**：

- 界面 = 标题 + `lv_bar`（轨道 = 深色、`LV_PART_INDICATOR` = accent 色，`bg_opa COVER`、
  `radius` 归零/小圆角、`border_width 0`）+ caption + 百分比。
- 动画由**本页自建 `lv_timer`** 驱动（如 40 ms、+2%/tick ≈ 2 s 跑满），
  不要靠外部线程改 bar —— 只有 LVGL 线程能碰对象。
- 交接口三件套：`xx_build()` 返回 screen 并 arm 动画、`xx_done()` 供判定、
  `xx_set(pct,caption)` 允许外部命名真实步骤（main.c 各阶段推进时用）。
- **交接在 mode_timer 里做**（50 ms）：`if (boot_active && boot_done()) { boot_active=false; build_main_screen(); }`，
  并让 `lv test/main` 之类人工切换**清 boot_active 抢占**。
- 页面切换用 `lv_screen_load(scr)`（v9 已无 `lv_scr_load`）。test 屏可一次性建好、
  `lv_obj_clean` 复用，避免切回时重新分配。

**"去掉复位时那段界面"的需求本质**：在 `bsp_lcd_init()` 之后、`lv_port_start()`
之前不要再往 framebuffer 画任何占位图案（连 `bsp_lcd_pattern(N)` 这种自查图也别调用），
让面板黑屏一帧后由 boot splash 立即接管。图案函数本体可保留给 `lcd pattern N` 命令。

## 6. 短命启动帧的 SWD 取证

启动动画只有 1~3 s，串口看不到画面，必须在**复位后精确时刻 halt** 再读 framebuffer：

```python
sess.open(); t = sess.target
t.reset_and_halt(); t.resume()
time.sleep(0.55)          # 落到动画中段；抓主页面用 4.0s
t.halt()
fb = bytes(t.read_memory_block8(FB_ADDR, W*H*2))
t.resume(); sess.close()
```

- 判"动作条在动"：轨道色 px **远大于**填充色 px，且填充 px 与动画百分比吻合
  （如 0.55 s ≈ 4% → 填充几百 px、轨道几千 px）。
- 判"已交接"：主页面帧里**轨道色 px 应为 0**，同时主页面配色（标题栏/时钟/值/标签）命中。
- **判"无彩条"要看整块大面积纯色**：彩条是整条 60×480 的填满带（数万 px）；
  标题白字的抗锯齿可能几百 px，别拿 <500px 当阈值误报（用 <5000px 或看是否有
  多色竖条带）。

## 7. 构建坑：`file(GLOB)` 不追踪新增源文件

MCU 工程常用 `file(GLOB SRCS applications/*.c ...)` 省事。**新增 .c 文件后增量
`cmake -S . -B build` 可能不生效**（GLOB 结果被缓存），链接报
`undefined reference to <新函数>`。**正解：清空并重建构建目录**
（`rm -rf build* && cmake -S . -B build`）。只重跑 `cmake`/`ninja` 不够。
（长期方案：`file(GLOB ... CONFIGURE_DEPENDS)`。）
