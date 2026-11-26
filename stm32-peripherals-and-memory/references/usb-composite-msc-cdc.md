# USB 复合设备（MSC + CDC，ST Device 库）实机判据

同一根 USB 线上同时给「大容量存储（FAT32 卷）」和「虚拟串口」，用 ST 官方 USB Device 库
（非 TinyUSB）。以下每条都在真机复现过；数值为 USB 全速（FS, 12 Mbit/s）实测。

## 上电顺序：文件系统先就绪，再启动 USB

```
介质初始化 → 挂载 → 无文件系统则格式化 → 自检读写 → 卸载卷 → 启动 MSC+CDC
```

反过来（先起 USB 再格式化）主机在探测期拿到"未就绪"，会把失败状态**缓存**下来：
盘符不出现，必须在主机侧手动"重新扫描磁盘"才恢复。这不是枚举失败，日志里也看不到错误。

卸载卷是必须的：主机要独占块设备，本地 FatFs 再写会破坏缓存一致性。

## 十条硬坑

1. **CubeMX 的 VBUS sensing 代码会重配你已在用的引脚。** 生成物里
   `HAL_PCD_MspInit()` 有一段把 VBUS 检测脚配成浮空输入；若该脚在板上是调试串口 TX，
   搬过来后日志从第一行起就发不出去。移植时要逐行比对 MspInit，不整体复制。

2. **没有 VBUS 检测脚却把 `vbus_sensing_enable` 留在 ENABLE**，OTG 内核认为"无 VBUS"，
   停在 B-session invalid，永不连接。关闭后由 LL 置 `GOTGCTL.BVALOEN|BVALOVAL` 强制会话有效
   （实测 `GOTGCTL = 0x030900C0`，正好这两位为 1）。

3. **不要用"把 D+ 切成 GPIO 输入读电平"判断主机是否连上。** 引脚从 AF 切到 GPIO 的同时
   也切断了 PHY，读回恒 0（假低电平）。判据看 `GINTSTS.SOF/USBRST` 与 `DSTS.SOFFN`。
   有外部 1.5K 上拉的板子这么测"能用"，换板即失效。

4. **复合设备必须给两个类各自独立的实例内存。** ST 模板的 `USBD_static_malloc()`
   永远返回同一块静态数组：MSC 句柄（约 8 KB，含 BOT 数据缓冲）会把 CDC 句柄（约 0.5 KB）
   整个盖住 —— U 盘在写、串口同时有流量时几百毫秒内 HardFault。
   修法：改成按块切分的静态池（记录每块大小，按请求长度取下一块，耗尽即断言）。

5. **挂起回调必须把 PHY 时钟放回来。** 模板 `HAL_PCD_SuspendCallback()` 无条件
   `__HAL_PCD_GATE_PHYCLOCK()`，而 Resume 分支没有对应的放行。主机一旦挂起总线
   （弹出/安全移除），PHY 停摆、检测不到 resume 的 K 状态，设备从此失联。
   若本来就不休眠（`low_power_enable = DISABLE`），suspend/resume 两侧都清 `PCGCCTL.STOPCLK`。

6. **MSC 类默认没有 `SYNCHRONIZE CACHE`（0x35 / 0x91）。** 主机 `FlushFileBuffers`
   与"安全弹出"会收到 `ILLEGAL REQUEST`，被记为"设备不支持 flush"。介质本来就是同步写时，
   在 SCSI 层直接回成功即可（数据早已落盘）。注意这类第三方/被忽略目录里的补丁
   在依赖恢复后会丢，要在构建流程里留一步重新打。

7. **`USBD_DescriptorsTypeDef` 的成员数随 `USBD_LPM_ENABLED` 变。** LPM 关闭时该结构少
   `GetBOSDescriptor` 一项，描述符表按 8 项初始化会报
   `excess elements in struct initializer`。`bcdUSB = 2.00` 时主机不会请求 BOS，关掉即可。

8. **PIO（轮询）模式反而消掉一整类问题。** `HAL_SD_ReadBlocks/WriteBlocks` 由 CPU 经
   SDMMC FIFO 搬运（非 IDMA）时：D-Cache 无需 clean/invalidate、缓冲无需 32 字节对齐、
   且可以放 **DTCM**（IDMA 根本到不了 DTCM）。代价是 CPU 占用，实测瓶颈在 USB 侧。
   只有在"CPU 忙不过来"时才需要换 IDMA，换之前先量吞吐。

9. **`ClockDiv` 交给 HAL 钳位。** 内核 100 MHz 下写 `ClockDiv = 1`（名义 50 MHz），
   HAL 会按卡的 `CardSpeed` 自动钳到 25 MHz（默认速）或保留 50 MHz（高速卡），
   不必自己判断卡型。

10. **探针连不上先怀疑速率。** 同一块板 `adapter speed 4000` 偶发
    `unable to connect to the target`，降到 500 kHz 稳定；连上后寄存器全部正常。
    这类"偶发连不上"不是固件问题。

## 吞吐基线（USB FS，判断"还能不能更快"）

| 用例 | 实测 |
|---|---|
| 顺序写（16 MiB，`fsync` 后计时） | 643 / 642 KB/s（两轮一致，不随写入量退化） |
| 顺序写（32 MiB，翻倍数据量） | 651 KB/s（无退化） |
| 顺序读（`FILE_FLAG_NO_BUFFERING` + SHA-256） | 820 KB/s，内容一致 |
| 4 KiB 随机改写（16 KiB 簇内） | 505 KB/s ≈ 126 IOPS |
| 串口双向满载时的写 | 413 KB/s（降 35%），设备不掉线 |

- **上限在哪**：FS 理论 1.15 MB/s，扣掉 BOT 每笔 CBW/CSW 开销，写 640 / 读 820 KB/s
  已接近物理上限。想突破只能换 OTG_HS，不是优化 SD 层能解决的。
- 串口满载的降幅是**两个接口分同一条 12 Mbit/s 总线**，不是 SD 变慢 —— 别去改卡时钟。
- 随机小块改写要"读-改-写"整个簇，是 FAT32 + 卡内部管理的固有代价。

## 基准脚本的两个前提

- **每轮先删文件再新建**，不要用 `O_TRUNC` 复用。Windows 上对已存在的文件
  `open(..., 'wb')` 可能返回 `PermissionError`（ACCESS_DENIED），与固件无关；
  换一块完全无关的可移动 FAT 卷能复现同样现象。此时 SWD 读回 SD 层
  `error_count = 0 / recover_count = 0`（写近万次全成功）可作反证。
- **掉电持久性单独验**：写若干 MiB → 硬复位（不是软复位）→ 重新挂载 → SHA-256 比对。
  只测正常弹出，验证不到写回路径。
