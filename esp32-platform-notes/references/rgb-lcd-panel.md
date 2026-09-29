# RGB 面板（esp_lcd_rgb_panel / DPI）故障判据

ESP32-S3 直驱 RGB 面板时，**"画面整体位移"最常见的原因不是时序参数，而是 DMA 带宽不足导致扫描失同步**。这两者在照片里长得一样，但处置完全相反，所以先按下表分流。

## 症状 → 根因对照

| 现象 | 根因 | 处置 |
|---|---|---|
| 整幅图固定位移，**右缘若干列绕回左边** | GDMA 跟不上 LCD 控制器的固定扫描率，扫描失步（permanent desync） | **只上 bounce buffer**；`RESTART_IN_VSYNC` 要**关掉**（见"反噬"节） |
| 位移**间歇出现**、时好时坏 | `RESTART_IN_VSYNC` 无条件重启本身造成的**单帧**错位（VBlank 中断迟到时） | 关掉该宏，让驱动用 `bb_eof_count` 欠载检测按需重启 |
| 改 porch 前后**毫无变化** | —— | 这就是"不是相位问题"的确证，别再调 porch |
| 画面有噪声 / 鬼影 / 细密竖纹 | PCLK 采样沿错 | 翻 `timings.flags.pclk_active_neg` |
| 全黑 | PCLK 过高，或 HBP 过短 | 降 PCLK 重试 |
| 上下位移 / 只有半帧 | VSYNC blanking 错 | 调 VBP / VFP |
| 只有刷新率不对 | —— | porch 影响的是 fps，不是位置（DE 模式下尤其如此） |

## 可检索原文（下次直接从这些措辞反查）

- `esp_lcd_panel_rgb.h` → `esp_lcd_rgb_panel_restart()`：
  *"the LCD controller is out of sync with the DMA because of insufficient bandwidth. To save the screen from a **permanent shift**"*
- `esp_lcd_panel_rgb.h` → `bounce_buffer_size_px`：
  *"DMA fetching from DRAM bounce buffer is much faster than PSRAM frame buffer."*
- `esp_lcd_panel_rgb.c:1265` → `lcd_rgb_panel_try_restart_transmission()` 上方注释，**副作用写在代码注释里而不是 Kconfig help 里**：
  *"Reset the GDMA channel every VBlank to stop permanent desyncs from happening.
  Note that this fix can lead to **single-frame desyncs** itself, as in: if this interrupt
  is late enough, the **display will shift** as the LCD controller already read out the
  first data bytes, and resetting DMA will re-send those."*
- Kconfig `LCD_RGB_RESTART_IN_VSYNC`：*"Only need to enable it when in your application, the DMA can't deliver data as fast as the LCD consumes it."*
  （**只说了好处**。要不要开，必须去读上面那两处代码。）

## 配方

1. **`bounce_buffer_size_px` 设为非零**（官方例程取 `h_res × 10` 行）。约束来自 `esp_lcd_panel_rgb.c`：
   `fb_size % bb_size == 0`（即每帧的反弹块数必须是整数，800×480×2 / 16000 = 48）。
2. **`CONFIG_LCD_RGB_RESTART_IN_VSYNC` 保持关闭。** 见下节，它和 bounce buffer 打架。
3. **IDF 6.x 起 `sram_trans_align` / `psram_trans_align` 已从 `esp_lcd_rgb_panel_config_t` 移除**，照抄 5.x 例程会编译不过；对齐由驱动自行处理。
4. **IRAM 约束**：`register_event_callbacks` 对回调的 IRAM 检查被 `#if CONFIG_LCD_RGB_ISR_IRAM_SAFE` 包着。未启用时回调可放 flash（安全）；**启用后** `on_vsync` / `on_frame_buf_complete` / `on_bounce_empty` 必须 `IRAM_ATTR`，否则直接返回 `ESP_ERR_INVALID_ARG` —— 调用方若用 `ESP_ERROR_CHECK` 包着，就是**开机 abort**。

## bounce buffer 的真实代价（官方文档没写）

`esp_lcd_panel_rgb.c:1028-1052` `lcd_rgb_panel_fill_bounce_buffer()`，在 **GDMA EOF 中断**上下文里：

```c
// copy partial frame buffer to the bounce buffer
memcpy(buffer, &panel->fbs[panel->bb_fb_index][panel->bounce_pos_px * bytes_per_pixel], panel->bb_size);
```

- **这是纯 CPU `memcpy`，不是 DMA**。每帧 `fb_size / bb_size` 次（800×480 = 48 次），
  每帧把**整帧** 768000 B 从 **PSRAM** 拷进内部 DRAM。39 fps 下 ≈ **30 MB/s 的拷贝流量全在 ISR 里**。
- 推论一：**`vTaskList` / `%CPU` 会把这份开销漏掉** —— FreeRTOS 运行时长统计不把 ISR 时间归给任何任务。
  "taskLVGL 只占 13%" **不等于**显示通路不忙。判断显示通路忙不忙，要去看驱动里有没有 ISR 内的大块拷贝。
- 推论二：这份 ISR 负载会**推迟 VSYNC 中断**。任何"无条件在 VSYNC 里做事"的开关，都会因此开始出错（见下节）。
- 它同时也顺带解决了 cache 一致性：拷贝走的是 CPU，写进 DRAM 反弹缓冲后再 `esp_cache_msync`，
  所以驱动在 bounce 模式下**不再需要 `fb_behind_cache` 那套 C2M 同步**。

## `RESTART_IN_VSYNC` 的反噬（本类项目最容易踩的一脚）

`esp_lcd_panel_rgb.c:1272-1289`：

```c
#if CONFIG_LCD_RGB_RESTART_IN_VSYNC
    do_restart = true;                                          // 每个 VBlank 无条件重启
#else
    if (panel->flags.need_restart) { ... }                       // 有人请求才重启
    if (panel->bb_eof_count < panel->expect_eof_count) { ... }   // 欠载检测
#endif
```

1. 打开该宏 = **每次 VBlank 都重启 GDMA**，并把 `#else` 分支**整个编译掉**。
   而那个分支里的 `bb_eof_count < expect_eof_count`（expect = `fb_size/bb_size` = 48）
   正是 **"这一帧没搬完 48 块"的精确判据** —— bounce 模式下天生的欠载检测。
   开宏 = 扔掉精确判据，改成每秒无条件重启 39 次。
2. 而"重发开头字节"导致的位移，和你**想修的那个位移症状一模一样**（整体右移 + 右缘绕回）。
   间歇性位移或"改了别的参数它就好了/又坏了"，先怀疑这里。
3. bounce buffer 正是让 VSYNC 中断变晚的原因 → **这个宏制造了自己要防的条件**。
4. 该函数只在 ESP32-S3 上存在：`#if CONFIG_IDF_TARGET_ESP32S3 / #define RGB_LCD_NEEDS_SEPARATE_RESTART_LINK 1`，
   注释写着 `// hardware issue workaround`。

**结论：bounce buffer 给 DMA 让出带宽，让驱动自己按需（`bb_eof_count` 欠载 / `need_restart`）重启；
两者不要同时开。**

## 两个修复同时上 = 无法归因

凡是"改了 A 也改了 B 然后症状消失"的场景，**最后必须做一次单变量回退**：关掉其中一条，
确认另一条是否足够、以及被关掉的那条是不是本来就在反噬。否则会把一个有害的开关
当成"必要的保险"长期留在配置里，而它的危害是间歇性的、下次出问题时最难怀疑到它头上。

## flush 的真实阻塞语义（"卡顿"不要想当然）

`esp_lvgl_port_disp.c:748-756`，在 `disp_type == RGB` 且 `direct_mode || full_refresh` 时：

```c
if (lv_disp_flush_is_last(drv)) {
    esp_lcd_panel_draw_bitmap(panel, 0, 0, hor_res, ver_res, color_map);
    /* Waiting for the last frame buffer to complete transmission */
    xSemaphoreTake(disp_ctx->trans_sem, 0);
    xSemaphoreTake(disp_ctx->trans_sem, portMAX_DELAY);   /* 阻塞 */
}
```

- 这段**不是**由 `avoid_tearing` 把关的，direct 模式下**必然**执行。
- `trans_sem` 由谁给？bb 模式 → `on_frame_buf_complete`（**整帧拷贝完成后**）；非 bb → `on_vsync`。
  **两者都是一整帧一次**。
- 所以：**改两个像素的按钮高亮，也要等满一整帧**（800×480@39 Hz = 25.6 ms）。
- 输入轮询（`lv_indev_read_timer_cb`，周期 = `LV_DEF_REFR_PERIOD`）跑在**同一个任务、同一个
  `lv_timer_handler()`** 里 → 落在 flush 期间的触摸要等 flush 出来才被看见。
- 因此"卡顿"的期望值是"交互时约等于面板帧率，最坏点按延迟 1~2 帧"。**低于面板帧率才叫有瓶颈**，
  先测出来再说，别凭手感改参数。
- 注意 `LV_DEF_REFR_PERIOD` 一个值管三件事（显示刷新 / **输入设备读取** / 动画步进），
  它是**请求不是上限**：面板 39 Hz 而它设 16 ms（62.5 Hz）时，日志里别把 62.5 当帧率读。

## esp_lvgl_port 配对约束

- `lvgl_port_display_rgb_cfg_t.flags.bb_mode` **必须**与 `bounce_buffer_size_px != 0` 一致。它不改变数据通路，只切换"哪个事件释放 LVGL 绘制缓冲"：
  - bb 模式 → `on_frame_buf_complete`（整帧已拷入反弹缓冲）
  - 非 bb → `on_vsync`
  两者不同步 → LVGL 等一个永不到来的事件（表现为卡死/黑屏）。
- `avoid_tearing = true` 会把**面板自身的 2 个帧缓冲直接当作 LVGL draw buffer**（DIRECT 模式，零拷贝、零额外分配）。硬前提：`num_fbs == 2`（端口用 `esp_lcd_rgb_panel_get_frame_buffer(panel, 2, ...)` 取），且 DMA 正在扫描的那块 CPU 不能写 —— 由 `trans_sem` + 帧完成回调串行化，因此**帧缓冲的地点在 PSRAM 时数据缓存行必须配成 64B**，驱动才认得出要做 C2M 同步。
- flush 路径：`lv_disp_flush_is_last()` 时调用 `esp_lcd_panel_draw_bitmap(panel, 0, 0, W, H, color_map)`。驱动发现该指针就是自己的帧缓冲时**只切换扫描源**（`cur_fb_index = draw_buf_fb_index`），**不会拷贝** —— 所以 CPU 侧确实没有多出来的整帧拷贝。**但"没有拷贝"不等于"不卡"**：紧随其后的 `trans_sem` 等待要阻塞一整帧，见上面"flush 的真实阻塞语义"。

## 带宽预算（先算，再改参数）

- 仅 DMA 一项：`h_res × v_res × 2 B × 刷新率`。800×480@39 Hz ≈ **30 MB/s**，且必须在每一行到来前准时到位。
- 同一条 PSRAM 总线上还有：CPU 渲染写入、cache 行回写（写分配会让每行"先读后写"）、以及打开 `SPIRAM_FETCH_INSTRUCTIONS` / `SPIRAM_RODATA` 时的**取指流量**。
- 顺序：先上 bounce buffer（官方解法）→ 再考虑关掉非必需 PSRAM 流量 → 最后才降 PCLK（降 PCLK 同时也降帧率，是最后手段）。

## 取证方法（不要用肉眼照片定性）

面板时序故障与布局故障在照片里**完全同形**。用**已知坐标的标尺**一次分离：

1. 在 LVGL 顶层画：贴屏幕四边的 1px 边框 + 四角固定色块（如 左上红 / 右上绿 / 左下蓝 / 右下黄）+ 中心十字。
2. 看照片里**边框与发光玻璃边界的关系**：
   - 边框贴玻璃边、内容内缩 → **布局**问题，去查对象坐标；
   - 边框自身内缩 / 被截断 / 绕回 → **面板时序/带宽**问题。
3. 相机预览截图有缩放和斜拍，**不要**用它做绝对像素测量；只量"标尺相对玻璃边界"的关系。要精确数字就用串口打印 LVGL 报告的几何值（并记得先 `lv_obj_update_layout()`，否则读到的是 `0..-1 / 0x0` 这种"还没布局"的合法值，很像"整页尺寸为零"的假 bug）。

## 生效判据（否则改了等于没改）

- **`sdkconfig.defaults` 只在 `sdkconfig` 不存在时参与生成。** 改完 defaults 必须删掉 `sdkconfig` 再重建；否则构建全绿、行为不变，且没有任何报错。可在构建启动器里加一条"defaults 比 sdkconfig 新则告警"的守卫。
- 验收：串口里驱动初始化日志应打印 `num_fbs`、`fb_size`、`bb_size`；落后症状消失；再抓一次帧率/渲染速率数字作为对照。
