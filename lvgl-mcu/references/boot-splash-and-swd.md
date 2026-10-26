# 开机启动画面（boot splash）、多屏交接与短命帧取证

驱动起来到主 UI 之间存在一段「framebuffer 里是占位内容」的窗口。有人直接 `fill()` 黑屏
或画测试彩条（复位时一闪而过的彩条就是这么来的）。正规做法是**启动动作条**，
且**在 LVGL 线程内自驱**。

## 界面构成

- 标题 + `lv_bar`（轨道 = 深色、`LV_PART_INDICATOR` = accent 色、`bg_opa COVER`、
  `radius` 归零或小圆角、`border_width 0`）+ caption + 百分比。
- 动画由**本页自建 `lv_timer`** 驱动（如 40 ms、+2%/tick ≈ 2 s 跑满）。
  **不要**靠外部线程改 bar —— 只有 LVGL 线程能碰对象。

## 交接三件套

- `xx_build()` 返回 screen 并 arm 动画
- `xx_done()` 供判定是否完成
- `xx_set(pct, caption)` 允许外部命名真实步骤（`main.c` 各阶段推进时用）

**交接在 `mode_timer` 里做**（50 ms）：

```c
if (boot_active && boot_done()) { boot_active = false; build_main_screen(); }
```

并让 `lv test/main` 之类人工切换**清 `boot_active` 抢占**。页面切换用 `lv_screen_load(scr)`
（v9 已无 `lv_scr_load`）。test 屏可一次性建好、`lv_obj_clean` 复用，避免切回时重新分配。

## 「去掉复位时那段界面」的本质

在 `bsp_lcd_init()` 之后、`lv_port_start()` 之前**不要再往 framebuffer 画任何占位图案**
（连 `bsp_lcd_pattern(N)` 这种自查图也别调用），让面板黑屏一帧后由 boot splash 立即接管。
图案函数本体可保留给 `lcd pattern N` 命令。

## 短命启动帧的 SWD 取证

启动动画只有 1~3 s，串口看不到画面，必须在**复位后精确时刻 halt** 再读 framebuffer：

```python
sess.open(); t = sess.target
t.reset_and_halt(); t.resume()
time.sleep(0.55)          # 落到动画中段；抓主页面用 4.0s
t.halt()
fb = bytes(t.read_memory_block8(FB_ADDR, W*H*2))
t.resume(); sess.close()
```

判据：

- **判「动作条在动」**：轨道色 px **远大于**填充色 px，且填充 px 与动画百分比吻合
  （如 0.55 s ≈ 4% → 填充几百 px、轨道几千 px）。
- **判「已交接」**：主页面帧里**轨道色 px 应为 0**，同时主页面配色（标题栏/时钟/值/标签）命中。
- **判「无彩条」要看整块大面积纯色**：彩条是整条 60×480 的填满带（数万 px）；
  标题白字的抗锯齿可能几百 px，别拿 <500 px 当阈值误报（用 <5000 px 或看是否有多色竖条带）。
