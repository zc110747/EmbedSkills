# MCU 上的字库引擎：CTF 磁盘索引 + 原 TTF 流式栅格化

场景：STM32 级芯片（无外部 SDRAM、内部 RAM 约 1 MB）上用 LVGL 显示中文/多语言，
字库放 **SD 卡（FatFs）**，核心是 **CTF 磁盘索引 + 原 TTF 流式栅格化**，
绝不把整个 TTF/CTF 装进 RAM。可整体搬到其它 STM32 / Zephyr + LVGL 工程。

## 一、不可违反的硬约束

1. **整个 TTF / 整个 CTF 都不进 RAM**。运行时只有：CTF 头缓冲 / 页缓冲 / entry 缓冲 /
   TTF 块缓存 / 字形缓存 / 栅格化临时 arena。
2. **缺字（CTF `NOT_FOUND`）必须立即返回，零存储访问**。这是硬性验收指标
   （`NOT_FOUND` 的 SD 读次数 == 0）。`CTF_NOT_FOUND` 是正常业务状态，
   不打印 error、不刷屏。
3. **第三方库目录（`third_party/`、`Drivers/`）禁止修改**；改动只落在自有代码与构建脚本。
4. **Debug / Release 双构零警告**（`-Wall -Wextra`）。
5. **Latin 预取误假设（高频坑）**：CTF 索引**通常包含拉丁范围**，LVGL 会用 TTF 渲染拉丁字形，
   Montserrat 回退只兜底索引**确实没有**的码点。`preload_enqueue()` **不得**
   `if (cp < 0x80) return;` —— 跳过拉丁会让每个含拉丁文本的页面首帧冷栅格化。
6. **首帧/首绘慢 ≠ 字库缓存 miss**：LVGL 一个 screen 第一次被实际绘制时的一次性 CPU 开销
   （样式计算 / label 排版 / draw-task 构建）可达 ~200 ms，**纯 CPU、零 IO**。
   解法不是加缓存，而是「抑制 flush 的离屏预热」。
7. **编码**：源码 UTF-8 字面量（`-finput-charset=UTF-8`）；**勿改** `-fexec-charset`。
8. **缓存 / MPU**：D-Cache **开启**（SDIO 轮询非 DMA，无一致性问题）。若将来上 DMA，
   用 MPU 把 DMA 缓冲标 non-cacheable，**绝不全局关 D-Cache**。

## 二、最终架构（自上而下）

```
LVGL label
  │  (lv_font_t: get_glyph_dsc / get_glyph_bitmap)
  ▼
CTF 后端层                     ← 仅此层接 LVGL，不碰 LVGL core
  ├─ 缺字 → return false → LVGL 走 Montserrat 回退（内部 Flash 数据）
  ├─ 命中 → 字形缓存 lookup ──hit──► 返回位图
  │                            └─miss─► 见下
  ▼
CTF Reader                     ← 三级直接寻址 O(1)，NOT_FOUND 零 IO
  ├─ L1 平面表（常驻 RAM ~2 KB）
  ├─ Page 表（常驻 RAM ~10 KB，all-or-nothing）
  ├─ TTF Table 目录（常驻 RAM ~132 B）
  └─ Entry（24 B：glyf 偏移/长度/glyph_id/度量/flags）
        │  FOUND
        ▼
TTF Reader                     ← 全工程唯一随机读收口
  └─ 块缓存（如 16 KB × 4 块，LRU）
        │
        ▼
栅格化适配层                    ← 流式宏接 ttf_reader，stb 源码零修改
  └─ stb_truetype（v1.26 系 fork）栅格化 → 8-bpp 位图
        │
        ▼
字形缓存（如 200 KB，放非主力 RAM 区）
```

**关键语义**：`Unicode → CTF → NOT_FOUND → END`（零存储访问）；只有确认存在才碰 TTF。

## 三、关键设计决策与理由

1. **CTF = 磁盘索引，不是字体数据**：只存 `Unicode → glyph_id / glyf 偏移 / 长度 / 度量 / flags`，
   位图/轮廓副本一概不存。三级直接寻址（plane → page(256-bit 位图) → entry），查找 O(1)，
   无遍历、无二分。位图为 0 = 字体没这个字 → 立刻 `NOT_FOUND`。
2. **resident RAM index**：L1 + Page 表 + TTF 目录常驻 RAM。
   仅当整张页表能放进页池才全常驻（**all-or-nothing**），否则退化走块缓存、**绝不部分常驻**。
   加载时一次性校验所有非空平面的 `page_offset` 落在池内，使第二跳减法永不溢出。
   效果：**缺字判定（bit 测试）完全在 RAM 完成，lookup 第二跳零 `f_read`**。
3. **TTF 块缓存（LRU）**：栅格化库经 `STBTT_STREAM` 宏接到 TTF Reader，
   **stb 源码零修改**。seek 变一次 store（零 IO），read 走块缓存（命中即内存拷贝）。
   能力：跨块合并、短块有效长度、LRU 替换、统计（hits / misses / fills）。
   `f_lseek() + f_read()` 全工程**仅一处**（单一收口）。
4. **字形缓存（放非主力 RAM 区）**：变长字形用 free-list + 偏移排序 + 前后合并精确回收；
   **LRU + epoch 钉扎** —— 当前页/正在用的字形持续抬升，永不被淘汰；切页 `bump_epoch()`
   让旧页落入淘汰域。异步预取：建页时扫描去重入队，定时器每几十毫秒在后台栅格化几个字，
   队列清空自删 timer。
   **为何放非主力 RAM 区**：避免主力 SRAM 使用率逼近 90% 的危险区；挪走后两个 RAM 区
   都能维持安全水位。**具体容量与分区按目标芯片重算。**
5. **内置 4 档 Montserrat 回退（12/16/24/32）**：编译进 Flash 的「内部数据」，
   SD 未挂载 / CTF 缺失 / 版本不符时 ASCII 与数字照常显示，UI 不空白。
   编译期断言 4 档全开，否则 `#error`。
6. **首帧预热**：构建完页面后，把 `disp->flush_cb` 换成 dummy 实现
   （吞掉帧缓冲推送、只调 `lv_disp_flush_ready` 收尾），逐页 `lv_scr_load + lv_timer_handler`
   各渲染一次，把「首绘一次性开销 + 字形冷栅格化」全挪到启动加载页背后（用户不可见）。
   首个真实翻页即 warm。**这是消除首帧 ~200 ms 卡顿的真正修复**（不是缓存优化）。
   依赖 `lv_disp_t::driver::flush_cb` 可被临时替换，不同 LVGL 版本 API 名可能微调。

## 四、已知坑 / 反模式

1. **Latin 预取误假设**：见 §一.5。带 `if (cp < 0x80) return;` 的预取函数假设「拉丁走 Montserrat」，
   但实测 CTF 索引含拉丁，LVGL 用 TTF 渲染 → 首帧拉丁字形冷栅格化，贡献页面卡顿。
   **正确做法**：拉丁一并入预取队列。
2. **首绘慢误判为缓存 miss**：首帧耗时高、字形缓存计数报 miss，看起来像未命中；
   但扩展日志加上「页 SD 读 / 块填充 / 块读」增量后证明三者全为 0 —— **零 IO**。
   差距是 LVGL 首绘 CPU 开销，须用「预热」而非「加缓存」解决。
   **判据：先看 IO 增量计数，再谈缓存调优。**
3. **EMPTY（空格）≠ NOT_FOUND**：空格有合法 advance、位图尺寸 0，必须正常排版，
   不能当缺字。
4. **kerning 是卡死元凶**：`stbtt_GetGlyphKernAdvance()` 走 GPOS 全表字节级扫描，
   字体几十 KB 即几万次 SD 随机访问 → 表现为「卡死」。LVGL 8 的 label 绘制无字距语义，
   **后端不调用 kerning**（能力可留在适配层仅供 benchmark）。
5. **GBK 引擎天然跳过预取**：当 `lvgl_font_px_of() == 0` 时预取函数 no-op；
   进度条纯按时间走，不预加载。切换引擎时要意识到预取路径整体失效。
6. **端口不硬编码**：调试串口号依本机分配、会变，脚本用 `pyserial list_ports`
   运行期枚举，禁止写死。

## 五、验证与回归

1. **双构零警告**：Debug 与 Release 两个构建目录均 0 warning，显式列出
   Flash / 各 RAM 区占比。
2. **烧录**：OpenOCD `program ... verify reset exit` → `Verified OK`。
3. **首帧计时（DWT CYCCNT）**：在主循环入口用 `DWT->CYCCNT` 包裹
   `lv_scr_load + lv_timer_handler`，打印 `scr_load / refr` 耗时，并报告字形缓存
   `hit / miss / evict` 与「页 SD 读 / 块填充 / 块读」增量。
4. **串口抓取顺序**：**先开串口后台抓**，再复位，否则错过启动 banner。
5. **回归脚本**：自动开串口 →（可选）烧录复位 → 抓固定时长 → 解析所有翻页日志 →
   断言 **首帧 miss == 0、零存储读、首帧耗时与预热后均值之差 ≤ 一个阈值**，
   退出码 0/1（CI 友好），支持从离线日志文件跑。⚠️ 该断言依赖固件侧的计时打印，
   移植时同步移植日志格式。
6. **NOT_FOUND 零 SD 验收**：对索引中不存在的码点断言 SD 读次数 == 0。
7. **运行时计数直读（无命令接口时）**：烧 Debug 构建 + gdb 直读字形缓存模块的静态计数
   （`s_hits / s_misses / s_evicts / s_free_bytes` 一类），比串口更准。

## 六、移植提示（到 Zephyr / 其它 STM32 LVGL）

- 字体引擎逻辑与 LVGL 版本弱耦合，主要依赖 `lv_font_t` 两个回调，可整体搬。
- Zephyr 下 SD 卡 / FatFs 路径、显示对接（SPI + 面板驱动）需对齐裸机参考实现。
- RAM 预算按目标芯片重算：字形缓存放非主力 RAM 区，避免挤占主 AXI-SRAM。
- 首帧预热依赖 `flush_cb` 可被临时替换；不同 LVGL 版本 API 名可能微调。
- 验证脚本的日志格式依赖固件侧 DWT 计时打印，移植时一并移植。
