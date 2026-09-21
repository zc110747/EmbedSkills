# 存储与文件系统：QSPI Flash、SD/FatFs、GBK 点阵字库、exFAT、U 盘

## 1. QSPI (W25Q64) Flash

- H7 的 QUADSPI 外设，4 线（引脚见 `pin-maps-and-buses.md`）。
- 用途：存放字库、网页、模型权重等大数据，释放内部 Flash。
- **memory-mapped（映射）模式下只读**；写入须先退出映射模式走命令序列再擦写。

## 2. SD 卡 + FatFs

- **SDMMC(4-bit) 目标缓冲必须 4 字节对齐**：HAL 以 `uint32_t*` 读 FIFO，未对齐地址会 HardFault。
  diskio 层对未对齐地址需经一块 512B 的 scratch 缓冲中转（这段中转代码不可删）；
  应用层传缓冲也尽量对齐。
- SDMMC 时钟：`SDIOCLK` 与 USB 同源（由 PLLQ 决定），再经 ClockDiv 分频到卡时钟；
  **轮询模式（不接 DMA）更稳**。
- 卷名不是跨平台常量，取决于 FatFs 配置：
  - 裸机默认：逻辑盘 `1:`（`FF_VOLUMES=2` 时 U 盘为 `0:`、SD 卡为 `1:`）。
  - Zephyr：`FF_STR_VOLUME_ID=1` + 卷名字宏（如 `"SD"`）→ 必须用 `SD:`，用 `1:` 挂载失败。
- `FF_FS_EXFAT 1` 才能挂载 exFAT 格式的 U 盘/存储卡。
- **`FF_CODE_PAGE` 必须为 `936`（GBK），绝不可改 437**，否则中文长文件名与字库路径乱码。

## 3. GBK 中文点阵字库

### 3.1 文件构成

放在卡上固定的字体目录（如 `SYSTEM/FONT/`）：

| 文件 | 作用 |
|---|---|
| `UNIGBK.BIN` | Unicode→GBK 映射表（4 字节/记录，**双段结构**） |
| `GBKxx.FON` | 12/16/24/32 点阵（MSB 优先、列扫描） |

### 3.2 UNIGBK.BIN 双段结构（极易踩坑）

- **段 1**（约前 21792 条）：`[unicode_lo, unicode_hi, gbk_lo, gbk_hi]` 小端，**按 Unicode 升序**。
- 段间有 1 条全 0 填充记录。
- **段 2**（其余）：`[gbk_lo, gbk_hi, unicode_lo, unicode_hi]` 小端，**按 GBK 升序**。
- ⚠️ 两段排序键不同，**不能对整个文件做 Unicode 二分查找**：初始化时先定位段 1 边界
  （第一条全 0 记录），只在段 1 内二分。
- ⚠️ GBK 字段在文件中同样是 `[gbk_lo, gbk_hi]` 小端，返回时需交换成常规顺序，
  否则汉字整体错位（症状是"显示成另一个形近/邻近的字"）。

### 3.3 渲染路径（自定义字体桥，如 LVGL）

1. UTF-8 → Unicode 码点（GUI 库解码）。
2. Unicode → GBK：在 UNIGBK 段 1 内二分（注意小端交换）。
3. GBK → 原始点阵：偏移 `190*(qh-0x81) + (ql-0x40或0x41)`；原始数据 **MSB 优先、列扫描**。
4. 转置为行扫描（保持 MSB 优先），得到 GUI 库需要的 1bpp 行优先位图。
5. ASCII 用移植的小字号点阵回退，避免矢量字体在小字号下发虚。

### 3.4 文本编码判定

渲染前先判断字节流类型，避免把 GBK 字节误当 UTF-8 转码
（GBK 双字节高字节 0x81–0xFE 常被误判为 UTF-8 续字节 → 乱码）：

- 无 BOM：先做 UTF-8 合法性校验；合法按 UTF-8 处理，不合法按 GBK 处理。
- 有 BOM（`EF BB BF`）：走快路径直接按 UTF-8，不转码。

## 4. USB 主机（TinyUSB）+ U 盘（exFAT）

以下结论在 F4 + FreeRTOS + 外部 SDRAM 平台验证：

- **USB 初始化必须在 `vTaskStartScheduler()` 之后**：`tusb_init()` 会开 OTG FS 中断，
  其 ISR 调用 `xQueueSendToBackFromISR` 等 `FromISR` API，调度器未启动时非法，会把系统跑飞。
  做法：把 `tusb_init()` 放进主机任务体内（该任务在调度器启动后创建）。
- **外部 SDRAM / FreeRTOS 堆初始化必须先于任何 RTOS 对象**：文件系统对象、GUI draw buffer
  落在外部 SDRAM，顺序错会写未初始化内存 → heap 断言。顺序：FMC 配置 → SDRAM 初始化序列 →
  刷新率 → 内存自测，全部早于一切 RTOS 对象。
- **FatFs 并发访问会死锁**：两任务并发访问同一 U 盘，而底层 `disk_read/write` 用单个全局 busy
  标志 + 自旋等完成回调时会丢唤醒。修法：用互斥量把**所有** FatFs 入口串行化（成对的
  lock/unlock 包住每个文件 API 调用）。
- **exFAT 真实性要验证**：`f_mkfs(FM_EXFAT, ...)` 后用原始卷解析验证 VBR 引导签名、
  簇堆对齐、分配单元大小（主机侧小 harness 输出 pass/fail 计数即可，不必看文件管理器）。
