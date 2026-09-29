# SPI 模式 SD 卡 bring-up

面向 **CS 由 I/O 扩展器（而非 SoC GPIO）驱动** 的板子，以及
"卡时好时坏、复位救不回来"的现场。

---

## 1. 唤醒序列是必需的，不是可选优化

SD 规范要求：**发 CMD0 之前，SCK 至少打 74 个周期，且这期间 CS 必须是高电平**
（频率 ≤400 kHz）。这是把卡片从 native SD 模式切进 SPI 模式的入口。

**反模式**：把 CS 交给扩展器，上电拉低一次就再也不管，同时用 `SDSPI_SLOT_NO_CS`
告诉 SPI-SD 驱动"没有 CS 引脚"。驱动拿到 `-1` 就**什么都不驱动** → CS 从头到尾为低、
74 个时钟也没人发。多数卡会凑合工作很久，直到某次复位正好卡在半条命令上。

修复形状（与具体 SoC 无关）：

```c
/* CS 高 + >=74 个 400kHz 空闲时钟 = 唤醒卡片并复位它的状态机 */
expander_cs(true);

/* 用一个"没有 CS"的临时 SPI device 把时钟打出去：
   注册时 spics_io_num = -1，驱动不碰任何片选，SCK 照样出时钟，
   而 CS 由上面的扩展器保持高电平。 */
spi_device_interface_config_t cfg = {
    .clock_speed_hz = 400 * 1000,
    .mode           = 0,
    .spics_io_num   = -1,          /* 不驱动片选 */
    .queue_size     = 1,
};
spi_bus_add_device(host, &cfg, &dev);

uint8_t tx[10];
memset(tx, 0xFF, sizeof(tx));      /* 10 字节 = 80 个时钟 */
spi_transaction_t t = { .length = sizeof(tx) * 8, .tx_buffer = tx };
spi_device_polling_transmit(dev, &t);   /* 注意：第二参数非 const，别写 const */
spi_bus_remove_device(dev);

expander_cs(false);
/* 到这里才 mount */
```

**每次重试都要重跑这一段**，不是只跑第一次 —— 重试的全部价值就在于把卡重新唤醒。
顺带：卡在插座里、开机时没有卡，这段也只是多花几十毫秒，没人会察觉。

## 2. "复位救不回来" ≠ 卡坏 / 接触不良

关键物理事实：**芯片复位（软复位 / `RTC_SW_CPU_RST` / 烧录后的复位）不切断 SD 卡供电。**
卡片仍挂在 3.3V 上没掉电，状态机就原地保持。由此：

- 现象为"**第一次能挂载，之后每次开机都失败，复位无效**"时，
  第一嫌疑是**卡片状态粘住**，不是换卡换线。
- 让卡片恢复只有两条路：**整机断电**（真掉电），或**唤醒序列**（CS 高 + 74 时钟）。
  后者更重要：产品必须能自愈，不能指望用户拔电源。
- **半条命令就足够卡住**：一次 panic、一次看门狗，只要发生在 CS 被拉低期间就有嫌疑。
  所以"某个崩溃之后开始读不到卡"是很典型的因果，不是巧合。

## 3. 日志只给两条线，不等于"驱动没问题"

同一个 UART 输出里，**不同响应类型走不同日志宏**：

| 响应 | 判定函数 | 宏 / 级别 |
|---|---|---|
| R4 / R5（SDIO 的 CMD5 / CMD52） | `r1_sdio_response_to_err()` | `ESP_LOGI` —— **默认可见** |
| R1（普通 SD 命令） | `r1_response_to_err()` | `ESP_LOGD` —— **默认被编译掉** |

于是默认 `CONFIG_LOG_MAXIMUM_LEVEL=INFO` 时，屏幕上只剩两条 SDIO 命令的报错，
**完整命令序列（CMD0 / CMD8 / CMD55 / CMD41）完全不可见**。

取证配方：

1. `CONFIG_LOG_MAXIMUM_LEVEL_DEBUG=y`，并**删掉 `sdkconfig` 重新播种**
   （Kconfig 只在 `sdkconfig` 不存在时用 defaults 播种，否则改了也静默无效）。
2. `LOG_DEFAULT_LEVEL` **保持 INFO**，改为在运行时对
   `sdspi_transaction` / `sdmmc_*` 这几个 tag 单独 `esp_log_level_set(..., ESP_LOG_DEBUG)`，
   否则全系统 DEBUG 会把 SD 那条线埋掉。

## 4. 别把 SDIO 探测当故障

`CONFIG_SD_ENABLE_SDIO_SUPPORT=y`（SDK 默认）时，**SPI 模式下驱动也会先发
CMD52 + CMD5 探测 SDIO**；普通 SD 卡必然回 `command CRC error` /
`command not supported`。这是**无害探测**，之后才走 ACMD41。

所以 **不能**用"日志里有 `cmd=52` / `cmd=5`"推断"驱动走错模式 / host flag 没设 SPI"。
判定走哪条分支看 `host_is_spi()` 的判据（`SDMMC_HOST_FLAG_SPI`），不要看命令号
（`SDSPI_HOST_DEFAULT()` 本身就带这个 flag）。

失败码对照 —— 都出自 `sdmmc_init_ocr()` 里的 ACMD41：

| 码 | 含义 |
|---|---|
| `0x102` | `ESP_ERR_INVALID_ARG` —— 卡没按预期应答 ACMD41 |
| `0x107` | `ESP_ERR_TIMEOUT` —— 连响应都没有 |

两者都指向"卡根本没在 SPI 模式里正常应答"，而不是"参数配错"。

## 5. 重试是安全的

`esp_vfs_fat_sdspi_mount()` 失败时走 `goto cleanup` →
`call_host_deinit(host_config)` + `free(card)`，**slot 已经被清理干净**，
可以直接再 mount 一次，不需要自己 deinit。

唯一要自己做的是**把 CS 释放掉（拉高）再重试**，让卡片看到一条空闲总线，
而不是被永久选中。

## 6. 编译期小坑

`spi_device_polling_transmit(dev, &t)` 的第二个参数**不是 const**。
写成 `const spi_transaction_t t` 会被 `-Werror=discarded-qualifiers` 直接拦下。

## 7. 一句话判据

> **CS 常低 + 无唤醒时钟** 的板子，读到 `0x102` / `0x107` 且复位无效时，
> 先补"CS 高 + ≥74 空闲时钟 + 重试"，不要先怀疑卡、线、或驱动配置。
