# ESP-IDF WiFi 站（STA）：静默故障与可断言判据

本文件只讲 **ESP-IDF 的 WiFi 站**，不涉及具体产品。所有坑都满足同一个特征：
**编译全绿、开机日志看着正常、状态机却卡住或算错账**。

---

## 1. 本机主动断开（reason 8 / 36）**不是故障**

`WIFI_REASON_ASSOC_LEAVE`(8) 与 `WIFI_REASON_STA_LEAVING`(36) 只可能由**你自己调用**
`esp_wifi_disconnect()` 产生，按定义不含任何网络信息。问题在于有**多个调用点**把它当成
**通往链路的一步**而不是离开：

| 调用点 | 为什么在这里断开 |
|---|---|
| `net_connect(new_ssid, ...)` | 已关联时 `esp_wifi_set_config()` 会被拒绝，必须先断 |
| `net_scan_start()` | 关联中扫描要么返回 `ESP_ERR_WIFI_STATE`，要么**静默杀死关联** |
| 用户按"断开" | 真的想要 idle |

前两处断开时，**"想要链路"的意图标志仍然是 true**，所以只判意图标志会把它们放进失败分支：

```
失败 #1 = 扫描自己的断开  →  重试计数 +1（什么都没买到）
真实失败                →  重试计数 +1，武装定时器
```

日志症状：**只有 `attempt 2/3`，永远没有 `attempt 1/3`**，计数器说重试了 3 次而实际只发出 2 次。

**正解**：把"是不是故障"与"想不想要链路"**分开判**。

```c
const bool deliberate = (d->reason == WIFI_REASON_ASSOC_LEAVE) ||
                        (d->reason == WIFI_REASON_STA_LEAVING);
if (deliberate || !s_want_connected.load(...)) {
    ESP_LOGI(TAG, "link down (reason %u); nothing to do", d->reason);
    return;                       /* 不发布状态、不计数、不武装重试 */
}
```

判据：**意图标志回答"要不要链路"，reason 回答"这份报告是不是故障"。**
两个问题合并成一个判断，就一定会在某个调用点错。

> 别用 reason 白名单去**推断**要不要重试（意图还得靠标志位）—— 但用 8/36 去**筛掉非故障**是完备的，
> 因为这两个码只会由本机断开产生。

---

## 2. `esp_timer_start_once()` 对**已武装**的定时器静默无效

对已经 armed 的定时器再次调用，它返回 `ESP_ERR_INVALID_STATE`，并且**不会重启**——
原到期时间保持不变。丢弃返回值就完全看不见。

典型场景：一个重试窗口内到达两次故障报告。

```
t0     故障 A → 计数=1，arm(t0+5000)
t0+184ms 故障 B → 计数=2，arm() 静默失败（定时器仍指向 t0+5000）
t0+5000 定时器到期 → 打出 "attempt 2/3"，但只发起了 1 次尝试
```

症状就是**两次故障的间隔远小于设定的重试延迟**。

**修法（二选一）**：

```c
esp_timer_stop(s_retry_timer);          /* 先停再装，最简单 */
esp_timer_start_once(s_retry_timer, us);
```

或者用一个 `pending` 标志**合并**同一窗口内的重复报告（第二次直接 return，不消耗预算）。
后者更严格：它保证"一个窗口只吃一格预算"，而不只是让定时器被重启。

**判据**：重试延迟是**可断言的**。日志里每次 `attempt` 与它前面最近一次 `disconnected`
的时间差必须 **≥ 设定延迟**。这条断言在定时器没重启时必然 FAIL，是唯一能自动抓住它的检查。

---

## 3. `WIFI_STORAGE_RAM` / 驱动 NVS 关闭时，**配置不跨复位**

想让凭据只有一个主人（应用自己管，驱动不留第二份）：

```c
esp_wifi_set_storage(WIFI_STORAGE_RAM);        /* 运行期 */
CONFIG_ESP_WIFI_NVS_ENABLED=n                  /* 编译期，日志会打印 config NVS flash: disabled */
```

代价：**每次关联都必须先 `esp_wifi_set_config()`，包括开机那一次。**

漏掉的失败方式是**静默的**：

- `esp_wifi_connect()` 返回 `ESP_ERR_WIFI_SSID`（没有配置可连）
- **不产生任何事件**
- 返回值通常被丢弃（`WIFI_EVENT_STA_START` 里写 `esp_wifi_connect();` 就完了）
- 状态机永远停在 `connecting`，**没有任何 handler 会来纠正它** —— 面板显示"正在连接"，
  而实际什么都没在连

**量级对照**（同一条链路，同一份凭据）：

| 路径 | 从"开始关联"到 `wifi:state: init -> auth` |
|---|---|
| 漏 `set_config` | 长时间**完全没有** auth 行 |
| 正确 `set_config + connect` | 约 1.2 s |

**正解**：把 `set_config + connect` 收进**唯一一个函数**，所有入口（开机、用户点连接、重连）
都走它。配置只有一个写点，就不会有入口漏掉。

```c
static esp_err_t apply_and_connect(const char *ssid, const char *password)
{
    wifi_config_t wc = {};
    snprintf((char *)wc.sta.ssid, sizeof(wc.sta.ssid), "%s", ssid);
    snprintf((char *)wc.sta.password, sizeof(wc.sta.password), "%s", password ? password : "");
    wc.sta.threshold.authmode = WIFI_AUTH_OPEN;   /* 开放 AP 是合法选择 */
    esp_err_t err = esp_wifi_set_config(WIFI_IF_STA, &wc);
    return (err == ESP_OK) ? esp_wifi_connect() : err;
}
```

> `esp_wifi_connect()` 的返回值**一定要看**。它是"配置没设/状态不对"这类静默故障的唯一出口。

---

## 4. 方法论：**诊断探针会替被测代码完成前置动作**

实测经历：带诊断探针（启动后自动跑一遍连接流程）时，开机自连"看起来正常"；
把探针移出、重抓纯净启动日志，同一份固件开机**永不自连**（就是上面第 3 条）。

原因：探针自己走的是**完整**的 `set_config + connect` 路径，顺手把被测代码该做而没做的事做了。

**判据：任何探针移出后必须重抓一次启动日志。** 否则你验收的是"探针 + 固件"，
而探针不在交付物里。

这条与既有反模式「探针不得留在交付固件」互补 —— 那条防的是探针**自己变成故障源**，
这条防的是探针**掩盖别人的故障**。

---

## 5. 内部 SRAM 与 RGB 面板的**记忆保证 = 分配顺序**

WiFi 站会从**内部 SRAM** 拿走可观的一块（默认 RX 缓冲配置下实测约 75 KB 量级），
而内部 SRAM 正是 RGB 面板的 bounce buffer / DMA 描述符所在的那个池子。

```c
CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP=y    /* 流量缓冲推去 PSRAM */
```

**关键不是省了多少，而是顺序**：显示通路必须在 WiFi 驱动之前拿完内存。

```
display_init()   /* 面板 FB + bounce buffer，先拿 */
...
net_init()       /* esp_wifi_init()，后拿 */
```

把 `net_init()` 提前**不只是改启动顺序**，而是改面板的内存保证 —— 在没有跑起来的分支上，
这是"改了也不知道"的一类改动。

**判据**：

- 开机日志里两个时间戳的先后（`RGB panel ready` 应早于 station 起来）
- `heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)` 的前后变化（本项目 204800 → 79872 B）
- **玻璃上那一眼**：面板位移类故障有时只在内部 SRAM 压力下出现，日志看不出来

---

## 6. 扫描 / 关联的互斥与收尾

- 关联中发起扫描：**两种行为都真实存在** —— 有时返回 `ESP_ERR_WIFI_STATE`，
  有时"成功返回但关联静默死掉"。所以不要指望按返回值判断。
- 正解：扫描前**主动** `esp_wifi_disconnect()` 让出射频（并把状态留在 `connecting`，
  因为这是暂停不是取消），扫描结束后重新 `esp_wifi_connect()`。
- **扫描结束是唯一的恢复点**：`on_scan_done()` 没跑（例如 `esp_wifi_scan_start()` 失败），
  关联就永远停在那儿 —— 所以扫描启动失败的分支也必须把关联恢复回来。
- `esp_wifi_scan_get_ap_num()` 与 `esp_wifi_scan_get_ap_records()` **都要调**：
  驱动是把缓冲**交出去**，只取数量不取记录会一直占着，直到下一次扫描。
- 隐藏 SSID 在扫描结果里表现为**空字符串**（配 `show_hidden = 1` 才看得到），
  列表里要能处理名字为空的条目。
- 驱动自己的 `wifi_ap_record_t` 远大于应用需要的字段，取完即转成自有结构并**丢掉**
  （放在 PSRAM，扫描不是延迟敏感路径）。

---

## 7. 可直接照抄的验收清单（全部来自日志，可脚本化断言）

| 项 | 期望 |
|---|---|
| 编译期配置真的生效 | 日志有 `wifi:config NVS flash: disabled` |
| 扫描 | `scan done: N found, M kept, strongest R dBm`，且结果按信号强度排序 |
| 关联 | `wifi:state: init -> auth` → `auth -> assoc` → `assoc -> run` → `connected with <ssid>` |
| 拿 IP | 自己发布的 `connected, ip x.x.x.x, rssi -NN dBm`，IP 不是 `0.0.0.0` |
| 失败 | reason 名（`no such network` / `wrong password`）→ 重试编号 `1..N` **无缺口** → `giving up after N retries` |
| 重试节拍 | 每次 `attempt` 与其前最近 `disconnected` 的间隔 **≥** 设定延迟 |
| 主动断开 | 每条 reason 8/36 都被记成"忽略"，**没有任何一条进失败分支** |
| 遗忘凭据 | `credentials erased` 之后**不应**再出现任何 `attempt`（观察窗口 ≥ 2× 重试延迟） |
| 健壮性 | 日志无 `ERROR***` / `Guru Meditation` / `Backtrace` / `assert failed` |

**写脚本时两条纪律**：

1. **常量从源码读**（正则抓 `kMaxRetries` / `kRetryDelayMs`），不要写死在脚本里。
   否则常量一改，脚本会跟着"通过"，验证就变成自证。
2. **一个日志都读不到时必须返回失败**。`0/0 checks passed` 会被打印成通过 ——
   假绿比没有脚本更糟。
