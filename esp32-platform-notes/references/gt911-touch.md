# GT911 触摸无响应 —— 症状、真值与取证

ESP-IDF + `esp_lcd_touch_gt911` + `esp_lvgl_port`，板子能正常显示、**I²C 也正常**，
但屏幕上怎么点都没反应。本文是这类故障的对照表与取证配方。

---

## 1. 症状 → 根因对照

| 现象 | 根因 | 处置 |
|---|---|---|
| 开机日志有 `TouchPad_ID:0x39,0x31,0x31` + `Config_Version`，`touch_init()` 返回 OK，但**永远读不到点** | 主机侧没给 **INT 上拉**（GT911 的 INT 是开漏输出，无上拉时空闲悬空） | `GPIO_MODE_INPUT` + `GPIO_PULLUP_ENABLE` |
| 同上，但上拉已给 | 复位窗口偏短（用了数据手册的 10 ms **脉冲**最小值，而不是上电窗口） | RST 低 100 ms → INT 拉低 → 100 ms → RST 高 → 200 ms |
| 能读到点，坐标却整体偏移 / 上下或左右反过来 | `flags` 的 `swap_xy` / `mirror_x` / `mirror_y` 与面板装配方向不符 | 逐项试；先确认面板是否原生横屏 |
| 能读到点，LVGL 却收不到任何事件 | 见 §4 的两条输入路径 | 按 §4 判断，不要盲改 |
| `esp_lcd_touch_read_data` 直接报错 / `ESP_ERROR_CHECK` abort | 设备没应答 | 查 FPC、查复位与**地址锁存** |

**关键陷阱：I²C 读得到 ID 不等于触摸链路通。** `TouchPad_ID` 只是读 `0x8140`
的固件信息，与触摸检测、与 INT 电平都无关。两者必须分开验证。

---

## 2. 官方真值（Waveshare ESP32-S3-Touch-LCD-4.3B）

来源：`waveshareteam/ESP32-S3-Touch-LCD-4.3B` →
`examples/ESP-IDF/09_lvgl_v9_demo/components/waveshare_rgb_lcd_port.{c,h}`

### 2.1 两条"反直觉但关键"的事实

```c
/* waveshare_rgb_lcd_port.h */
#define EXAMPLE_PIN_NUM_TOUCH_RST       (-1)   /* -1 if not used */
#define EXAMPLE_PIN_NUM_TOUCH_INT       (-1)   /* -1 if not used */
```

**官方也是 `GPIO_NUM_NC` —— 官方同样走轮询，不配中断。**
`tp_cfg.int_gpio_num = -1` 会让 `esp_lvgl_port` 不注册中断回调、indev 停在
`LV_INDEV_MODE_TIMER`。**所以"换成中断驱动"不是必须的，别把它当成默认修复。**

### 2.2 复位与地址锁存（`waveshare_esp32_s3_touch_reset()`）

```
CH422G 写 0x38 = 0x2C   → EXIO1 = 0，CTP_RST 拉低
delay 100 ms
GPIO4 = 0               → INT 拉低（地址将在 RST 上升沿被锁存）
delay 100 ms
CH422G 写 0x38 = 0x2E   → EXIO1 = 1，CTP_RST 拉高  ← 此刻锁存地址
delay 200 ms
```

- 地址由 **RST 上升沿时 INT 的电平**决定：低 → `0x5D`，高 → `0x14`。
- 官方把 INT 留成**输出并持续驱动低**（`gpio_init()` 只设 `mode = GPIO_MODE_OUTPUT`，
  之后再 `gpio_set_level(GPIO4, 0)`）。这**安全的前提是 GT911 的 INT 是开漏输出**。
- 官方 `tp_cfg.driver_data` 为 `NULL`，所以驱动打印
  `I2C address initialization procedure skipped - using default GT9xx setup`
  —— **这行是正常的**，不代表配置漏了。
- `rst_gpio_num = -1` 时驱动自己的 reset 是空操作，复位完全靠上面这段手工序列。

### 2.3 其它字段

| 字段 | 官方值 |
|---|---|
| `x_max` / `y_max` | 800 / 480（面板原生分辨率） |
| `levels.reset` / `.interrupt` | 0 / 0 |
| `flags.swap_xy / mirror_x / mirror_y` | 0 / 0 / 0 |
| `process_coordinates` | NULL |
| `tp_io_config.scl_speed_hz` | 0（用默认） |

---

## 3. INT 引脚的语义

- GT911 的 INT 是**开漏中断输出**，触摸时拉低。**板子/主机侧必须提供上拉**才有确定电平。
- 主机把 INT 长时间拉低，在 GT911 看来是"主机忙"。官方敢这么做只是因为开漏不冲突；
  让引脚回归输入 + 内部上拉是更克制的做法。
- 空闲时 `gpio_get_level(INT)` 应为 **1**；手指按下应为 **0**。
  这条电平变化本身就是"控制器确实检测到触摸"的**硬件级证据**，且**零副作用**。

---

## 4. esp_lvgl_port 的两条输入路径

`esp_lvgl_port` 主循环（`src/lvgl9/esp_lvgl_port.c`）：

```c
events = xEventGroupWaitBits(lvgl_port_ctx.lvgl_events, 0xFF, pdTRUE, pdFALSE, wait);
if (events & LVGL_PORT_EVENT_TOUCH || events & LVGL_PORT_EVENT_ENCODER) {
    ... lv_indev_read(indev) ...        /* 主动读 */
}
task_delay_ms = lv_timer_handler();     /* 这里会跑到 indev 自带的 read_timer */
```

- `LVGL_PORT_EVENT_TOUCH` **只由触摸中断回调**（`lvgl_port_touch_interrupt_callback`）置位。
- 但 `lv_indev_create()` 会给每个 indev 建一个 read_timer
  （`lv_indev.c:133`，周期 `LV_DEF_REFR_PERIOD`），而 `lv_indev_set_mode()` 的
  `lv_timer_pause()` **只在 `LV_INDEV_MODE_EVENT` 时执行**。
- ⇒ **`int_gpio_num = NC` 不会导致输入永不读取**。TIMER 模式的 indev 由
  `lv_timer_handler()` 正常驱动。看到主循环里那个 `if` 就断定"轮询不可用"是误判。

`lvgl_port_touchpad_read()` 本体很薄：`esp_lcd_touch_read_data()` →
`esp_lcd_touch_get_data()` → 点数 > 0 则 `PRESSED` 否则 `RELEASED`。

---

## 5. 三层被动取证配方

**目标：一次烧录定位"断在哪一层"，而不是猜一版烧一版。**

| 层 | 观测对象 | 判据 |
|---|---|---|
| 硬件 | `gpio_get_level(TOUCH_INT_GPIO)` | 空闲 1 / 按下 0。恒定不变 ⇒ 控制器没看到手指 ← 不要往上找 |
| 驱动 | `touch->data.points`（及 `coords[0]`） | 按下时非 0 ⇒ 驱动在被读且确实上报了触点 |
| 框架 | 给 indev 挂 `lv_indev_add_event_cb(..., LV_EVENT_ALL, ...)` 计数 | 计数增长 ⇒ 事件已到达 LVGL；恒 0 ⇒ 断在框架之前 |

**必读判据：**

- points > 0 而 indev 恒 0 ⇒ 驱动好、框架没拿到 ⇒ 查 §4 与页面层的输入阻塞
  （`indev->enabled`、`disp->prev_scr != NULL`、坐标系是否越界）。
- 三层全 0 ⇒ 控制器侧问题 ⇒ 回到 §2 的时序与 §3 的上拉 / §1 的 FPC。

**零副作用的探针骨架**（放在触摸驱动的 owner 里，验证完删除）：

```c
/* 只在内存里读，不碰 I²C */
static void diag_timer_cb(lv_timer_t *t)
{
    (void)t;
    const uint32_t pts = (s_touch != NULL) ? (uint32_t)s_touch->data.points : 0u;
    ESP_LOGW(TAG, "DIAG irq=%d  drv points=%u last=(%u,%u)  indev press=%u release=%u",
             gpio_get_level(BOARD_TOUCH_IRQ_GPIO), (unsigned)pts,
             (unsigned)(pts ? s_touch->data.coords[0].x : 0),
             (unsigned)(pts ? s_touch->data.coords[0].y : 0),
             (unsigned)s_evt_press, (unsigned)s_evt_release);
}

/* 注册必须进 LVGL 锁；lvgl_port_lock 是递归锁，不是所有权转移 */
if (lvgl_port_lock(0)) {
    lv_indev_add_event_cb(s_indev, diag_indev_cb, LV_EVENT_ALL, NULL);
    lv_timer_create(diag_timer_cb, 1000, NULL);
    lvgl_port_unlock();
}
```

### 反模式：写一个"直接读状态寄存器"的探针

GT911 的 `0x814E` 是 **buffer-ready 位 + 读后写 0 清除** 协议
（驱动实现：读 `0x814E`，`bit7 == 0` 即判无触摸；读到坐标后写 0 清除）。
任何自己读这个寄存器的探针，每采一次就**抢走一次驱动的事件位**——
**诊断本身变成故障源**。要读也只能"写 0 → 读 → 写 0"完整复刻驱动行为，
且必须接受它和驱动互相竞争。

---

## 6. 幽灵触摸 vs 真实触摸

读到坐标不等于修好了，要区分"手指"与"幽灵"：

| 观察 | 结论 |
|---|---|
| 空闲时 INT 多为高，偶发低 + 点数 1 | **真实触摸**（有人按） |
| INT 长期低、点数长期 ≥ 1 | **幽灵触摸**（基线漂移 / 配置损坏 / 供电噪声） |
| 页面出现有逻辑的导航序列（进 A → 返回 → 进 B） | 真实点击；随机幽灵触点做不出这种序列 |

幽灵触摸的处置方向：检查供电与地回路、GT911 配置寄存器是否被复位打断、
面板是否被持续压迫（装配应力），必要时做基线重校准。
