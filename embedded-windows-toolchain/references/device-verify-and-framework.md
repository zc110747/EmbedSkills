# 编译期约束、设备验证与框架大版本迁移

## 一、编译期零警告

硬约束：**Debug / Release 双构零警告**。

```cmake
if(MSVC)
  target_compile_options(x PRIVATE /W4 /EHsc /utf-8)
else()
  target_compile_options(x PRIVATE -Wall -Wextra)
endif()
```

- MSVC 默认按 GBK 读源码，UTF-8 源会刷 `C4819` 警告 → 统一加 `/utf-8`。
- MSVC `/W4` 两个高频项：基类虚方法**形参未使用** → C4100，用 `(void)param;`；结构体成员若
  命名为 `auto` 属关键字 → 编译错误，改名。
- 链接脚本（`.ld`）改动后必须让 CMake 跟踪该文件，否则改脚本不触发重链。
- `-specs=nano.specs` 默认不链浮点 printf，需补 `-u _printf_float`，否则含浮点打印时字段显示空白。
- mbedTLS 3.x 的 `-Warray-bounds` 假阳性（128 位 union）可在配置头用
  `#pragma GCC diagnostic ignored "-Warray-bounds"` 屏蔽。

**宏实际生效值**：`#pragma message` 在 `-E` 下**不求值**，要确认宏值必须用 `-dM -E`：

```bash
arm-none-eabi-gcc <原样搬来所有 -D 和 -I> -dM -E build/probe.c -o build/probe.i
grep -E "define (IP_REASSEMBLY|CHECKSUM_)" build/probe.i
```

## 二、烧录、串口与日志

- 调试器配置：openocd 0.12 用 `transport select swd`，**不支持旧 `hla_swd`**（会报
  "adapter doesn't support"）。
- **识别串口必须用 pyserial**：`Get-WmiObject` / `serial.tools.list_ports.GetPortNames()` 会漏掉
  USB 串口；端口号会变，**不要硬编码**。
- 抓日志用带时间戳的脚本，才能区分"卡住"与"真的没输出"：

```python
ser = serial.Serial(port, 115200, timeout=0.5)
ser.setDTR(False); ser.setRTS(True); time.sleep(0.1); ser.setRTS(False)   # 复位
t0 = time.time()
while time.time() - t0 < SECONDS:
    d = ser.read(4096)
    if d: print("[%6.2fs] +%d" % (time.time()-t0, len(d)), d.decode(errors="replace"))
```

- **日志级别坑**：先确认 `CONFIG_LOG_DEFAULT_LEVEL`。若为 `2`（WARN），所有 INFO/DEBUG 级日志
  **不可见**，看起来就像"板子卡住了"。关键状态日志临时改用 WARN 级输出。
- `arp -a <IP>` 核对应答者 MAC OUI（排除同 IP 其它设备顶替造成的假通）。

## 三、外部行为验证（串口日志不可信时）

- 热点是否广播：`netsh wlan show networks mode=bssid | grep -i <SSID>`。Windows 扫描有缓存，
  变化后等 20–30 s；但**扫描结果只能证明"它存在过"，不能证明"设备还活着"**——判死活以设备侧
  串口日志为准。
- **无线关联失败的真实原因在系统"无线自动配置"事件日志里**，不在命令行返回里：
  "网络不可用 / RSSI=255" = 根本没扫到该 BSS，与"密码错误"是两回事，凭猜很费时间。
- 连一个**没有外网的热点会改默认路由**：先看路由表/跃点确认归属；改跃点需要管理员权限，
  拿不到就别硬改，改为接受"验证期间本机公网可能瞬断"。
- USB HID / CMSIS-DAP 链路体检（不接目标板）：

```tcl
adapter driver cmsis-dap
transport select swd
adapter speed 1000
swd newdap chip cpu -irlen 4
dap create chip.dap -chain-position chip.cpu
target create chip.cpu cortex_m -dap chip.dap
init
```

见到 `CMSIS-DAP: FW Version` / `Interface ready` 即链路正常；末尾
`Error connecting DP: cannot read IDR` 只是没挂目标芯片，属预期。

## 四、ESP32-S3 专项

- `tud_connected()` **≠ 有主机**，它只表示 VBUS 存在（插充电头也为真）。判断"USB 主机已枚举"
  必须用 `tud_mounted()`。
- **Wi-Fi 与 USB OTG 冲突**：Wi-Fi 一起，USB HID 传输时序被 RF 破坏，主机侧表现为 CMSIS-DAP
  通讯错误/超时。需共存时做成互斥仲裁（检测到主机就绝不启动 Wi-Fi）。
- 上电常见 `gpio: conflict found for GPIO[x]` 多为引脚被重复配置，未必是致命错误。

## 五、ESP-IDF 常见构建错误

| 报错 | 根因 | 修法 |
|---|---|---|
| `implicit declaration of ESP_RETURN_ON_ERROR` | 缺 `esp_check.h` | 加 `#include "esp_check.h"`；组件 `REQUIRES` 加 `esp_common log` |
| `'/*' within comment [-Werror=comment]` | 注释里出现 `*/` 或 `/*` | 改写注释文字 |
| `xxx.h: No such file` + `component_requirements.py BUG` | 用 `if(CONFIG_XXX)` 条件化 `REQUIRES` | 见下 |
| 改了 sdkconfig 行为没变 / 构建秒完 | cmake 用旧缓存 | 重新 `reconfigure` 后再 build |

**Kconfig 宏只能用于 C 的 `#if`，不能用于 CMake 的 `if()`**：组件注册阶段取不到 `CONFIG_XXX`
的 CMake 变量，条件化 `REQUIRES` 会静默丢掉 include 路径。正确做法是 `REQUIRES` 无条件列出，
门控写在 C 代码里：

```c
esp_err_t feature_init(void)
{
#if !CONFIG_MY_FEATURE
    ESP_LOGW(TAG, "disabled by CONFIG_MY_FEATURE=n");
    return ESP_ERR_NOT_SUPPORTED;
#else
    ...
#endif
}
```

## 六、IDF 5.x → 6.x 驱动 API 迁移

启用一个原本关闭的编译分支（例如把某个开关从 0 改成 1）后，**编译错误往往不止一层**：先修
`implicit declaration`，再修 `invalid scl frequency` 这类**运行时 abort**。一次只修一层，
每层都真机验证。

### 6.1 legacy `driver/i2c.h` 被整体移除

| 旧 API | 新 API |
|---|---|
| `i2c_driver_install()` / `i2c_param_config()` | `i2c_new_master_bus(&bus_conf, &bus)` |
| `i2c_master_write_to_device(port, addr, buf, len, ticks)` | `i2c_master_bus_add_device()` → `i2c_master_transmit(dev, buf, len, timeout_ms)` → `i2c_master_bus_rm_device(dev)` |
| 头文件 `driver/i2c.h` | `driver/i2c_master.h` |
| `I2C_MASTER_TX_BUF_DISABLE` / `RX_BUF_DISABLE` | 删除（不再需要） |

超时单位变了：旧 `ticks = MS / portTICK_PERIOD_MS`，新 `timeout_ms` **直接给毫秒**。
推荐封装（用完即摘设备，避免句柄堆积）：文件级持有 bus 句柄，每次写临时 `add_device` →
`transmit` → `rm_device`。

别忘了组件 CMakeLists 加 `PRIV_REQUIRES esp_driver_i2c`：v6.x 组件化拆包后
`esp_driver_i2c` / `esp_driver_gpio` 不再随基础组件隐式进来。

### 6.2 `esp_lcd_new_panel_io_i2c()` 新增必填 `scl_speed_hz`（最易漏）

旧版本组件（如上游触摸驱动）的配置宏**没有** `scl_speed_hz` 字段。编译**完全通过**，一上电即 abort：

```
E (914) i2c.master: i2c_master_bus_add_device(1181): invalid scl frequency
E (914) lcd_panel.io.i2c: esp_lcd_new_panel_io_i2c(72): i2c add device fail
ESP_ERROR_CHECK failed: esp_err_t 0x102 (ESP_ERR_INVALID_ARG)
```

链路：`esp_lcd_panel_io_i2c.c` 把 `io_config->scl_speed_hz` 零初始化透传给
`i2c_device_config_t`，而 `i2c_master.c` 有 `dev_config->scl_speed_hz > 0` 校验 → 0 → abort。

修复必须**展平宏、不能嵌套**（展开后是裸 `{ ... }`，无设计符，塞进另一个初始化列表会报
`braces around scalar initializer` / `field name not in record`）：照宏内容手写一遍，补上
`scl_speed_hz`（必须 > 0）以及 v6.x 新增的 `transaction_timeout_ms`。

**通用教训**：凡 v6.x 报 `ESP_ERR_INVALID_ARG`（0x102）的**运行时**失败，且参数来自第三方/上游
组件的配置宏，第一件事是去 IDF 头文件 diff 该 struct，找新增的必填字段——编译期不会提醒，
零初始化是合法的。

### 6.3 `esp_lcd_rgb_panel_config_t` 瘦身（5.2 → 6.x）

删除以下成员（用了就报 `has no member named ...`）：

- `bits_per_pixel` —— 由 `data_width` 自动推导 RGB565
- `sram_trans_align` / `psram_trans_align` —— burst 缺省 64

回调也变了：`on_bounce_frame_finish` 被移除 → 统一用 `.on_vsync`，回调函数加 `IRAM_ATTR`
（VSYNC ISR 上下文）。
