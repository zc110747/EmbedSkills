---
name: lvgl-mcu
description: LVGL v8/v9 屏上不对：豆腐块/缺字、首屏冻结、复位彩条、颜色全错、曲线塌陷、framebuffer 移植。含子集字库与 SD 卡 TTF 流式引擎。
agent_created: true
---

# LVGL on MCU：渲染静默失败、字库引擎与 v9 迁移

LVGL 渲染层**几乎不报错**：缺字形、值越界、区域被裁都是**安静地不画**，而
`lv_obj_get_width()`、`lv_font_get_glyph_dsc()` 一切正常，单测全绿。
渲染类问题只能**看像素**，数据流类只能**核数据来源**。v8/v9 通用，PC 模拟器（SDL）
与 MCU 移植同理。

## 何时用

- 编译通过、运行不崩，但屏幕空白 / 有框无字 / 字变空心方框 / 内容永远是旧的
- 图表曲线塌陷、凭空消失、尾部丢失，或浮动标签与曲线互相遮挡
- v8 升 v9 后首屏冻结、复位时闪一段彩条、颜色全错
- 子集字库的字符集提取与覆盖校验；字库放外部存储（SD/FatFs）
- `lv_init()` 顺序、PC 模拟器后端、framebuffer 首次移植

## 四类静默失败（症状 → 根因 → 判据）

| 症状 | 根因 | 判据 |
|---|---|---|
| 有框无字，配色全对 | `LV_USE_FONT_COMPRESSED` 与字体生成器不匹配，位图回调返回 NULL，LVGL 对 NULL 直接不画 | 逐码点断言位图回调非空 |
| 空心方框（豆腐块） | 码点不在字体 cmap 内；占位符宏开启时会画一个**像 UI 元素**的空心矩形并打 warn | 控制台 `glyph dsc. not found` 计数为 0 |
| 曲线塌陷 / 消失 / 尾部丢失 | 样本用 `lv_coord_t`（int16）承载小量程数据被取整；缩放值撞上 `LV_CHART_POINT_NONE`（= `INT16_MAX`）被当无数据跳过；绘图层按点数上限截断，切掉的是尾部 | 轴上限远离 `INT16_MAX`；点数上限 ≥ 一个数据窗口的样本数 |
| 内容永远是旧的 | 事件到了、UI 重建了，但重建时读回的模型没被重载；或「是否重建」只比集合不比位置 | 逐跳核数据来源；**位置也是状态** |

## 字体与子集字库

- 字符集**只能从源码自动提取**，扫描前**必须剥掉注释**；提取、生成、覆盖校验
  **共用同一份扫描逻辑**，否则校验静默失效——仍在打印 PASS，守的却不是同一件事。
- 扫描要**跳过字体产物目录**，生成物永远不是输入。
- 运行期才出现的字（用户输入、模型输出、配置文本）不可能被静态收集：把码点写进测试，
  断言 cmap 命中 **且** 位图非空 **且** 位图字节中有非零。
- 改过任何界面文案都要重跑覆盖校验；字库取值范围变化后回看资源占用。
- EMPTY（空格）≠ NOT_FOUND：空格有合法 advance、位图尺寸为 0，必须正常排版。

## 无 SDRAM 的字库引擎（CTF 磁盘索引 + 原 TTF 流式栅格化）

- 硬约束：整个 TTF / 整个 CTF 都**不进 RAM**；缺字在索引层立刻返回、**零存储访问**；
  内置 Montserrat 兜底编进 Flash，保证 SD 未挂载或索引缺失时 UI 不空白。
- CTF 是**磁盘索引**而非字体数据：只存码点 → 字形偏移/长度/度量/flags，
  平面表 → 位图页表 → entry **三级直接寻址 O(1)**，位为 0 即缺字。
- 位图页表**要么全常驻、要么全走块缓存**，绝不部分常驻。
- TTF 侧收口：随机读只有一个 `f_lseek + f_read` 入口、块缓存 LRU、字形缓存 LRU + epoch 钉扎；
  栅格化库经流式宏接入，第三方源码零修改。
- **首绘慢 ≠ 缓存 miss**：先用零 IO 计数（页访问 / 填充 / 读次数增量）证伪，再决定加缓存或预热。
- kerning 查询会全表字节级扫描、触发海量随机读；LVGL 8 的 label 绘制无字距语义，后端不应调用。

## 初始化顺序

- `lv_init()` 必须在任何 `lv_*_drv_register()` 之前——内存池由它创建。
  崩溃栈出现 `tlsf=0x0` / `control=0x0` 即本坑。
- 开了 `LV_TICK_CUSTOM` 不要再调 `lv_tick_inc()`，否则重复计时、定时器跑飞；
  其 `INCLUDE` 头会被 LVGL 的 `.c` 包含，必须 C/C++ 双兼容。（**v9 已删该宏，改用
  `lv_tick_set_cb`，见下。**）
- 桌面后端自写，避免第三方 SDL 后端接管主循环并在关窗时直接 `exit(0)`。
- 信号崩溃可能被 shell 吞成 `exit 0`，只留「日志停在某行」的假象：用耗时 + 调试器栈判定。

## v8 → v9 必改点

| 变化 | 症状 / 正解 |
|---|---|
| `LV_TICK_CUSTOM` **已删除** | 写了就是死代码 → 首屏渲染一次后**永久冻结**（动画/timer 全停）。改用 `lv_tick_set_cb(cb)`，cb 返回毫秒 |
| `lv_color_hex()` 收 **RGB888** | 传 RGB565 常量 → 色相全错（`0xF800` = 亮绿）。像素断言用 `0xFF0000/0x00FF00/0x0000FF/0xFFFFFF` |
| `lv_display_create` + `set_flush_cb` + `set_buffers` | PARTIAL 行缓冲 40~50 行，buffer 尺寸按**字节**；flush 的 area 是绝对坐标、无 stride |
| `lv_screen_load()` | 取代 `lv_scr_load()` |
| `lv_theme_default_init()` 已作用于 display | 勿再 `lv_display_set_theme` |
| `lv_mem_monitor_t` 无 `used_size` | 用 `total_size/free_size/used_pct/max_used` |
| anim exec 第三参 | 控件 setter 多带 `anim` 参，直接 cast 会把垃圾传入 → 包一层 `void cb(void*, int32_t)` |
| 静态库 vs section 表 | LVGL 纯 API 调用 → `.a` 安全；依赖 linker section 的注册机制放 `.a` 会被 `--gc-sections` 静默 gc |

`file(GLOB)` 不追踪新增 `.c` → 链接报 `undefined reference`，必须清空重建目录
（只重跑 `cmake`/`ninja` 不够）。

## 判据与反模式

- **像素判定用谓词与预量化，不用纯色字面量**：抗锯齿字形绝大多数像素是「文字色 × 底色」
  的混合色；颜色深度一变，所有字面量同时失配。
- **「有没有让位/留白」必须渲染两次对比** —— 上层元素盖住的东西在像素上不可见，
  「某色像素变少」证明不了任何事；对齐偏移在调用那一刻固化，改完文本要重新锚定。
- **显示态逐态出版本**，不是只灌一组极限值：空白 / 失败 / 数值 / 判定态走不同渲染分支。
- **「没测」与「测失败」不得合并成同一显示**：二值 `has_x` 升级成三态，失败优先暴露。
- **灌假值的调试探针不得留在交付固件** —— 某天被打开，界面会显示一组看起来完全正常的
  假测量值；要保留就做成构建期可选且默认关闭。
- 验收挂进 ctest / 回归脚本，双构零警告；出样张人眼确认一次，数字对不代表看起来对。

## 详细资料

- `references/silent-failures.md` —— 四类静默失败逐条症状/根因/定位，图表与布局细节、三态语义
- `references/font-subset.md` —— 子集字库、字符集提取与覆盖校验、压缩标志、字形（GLYPH）探针
- `references/font-engine-sd-ttf.md` —— CTF 索引 + TTF 块缓存字库引擎的硬约束、设计决策与验收回归
- `references/init-order.md` —— `lv_init` 顺序、`LV_TICK_CUSTOM`、SDL2 后端与构建链接坑
- `references/onscreen-forensics.md` —— 离屏探针骨架、MCU 整帧取证与取证结论复核
- `references/v9-migration.md` —— v9 破坏性变化全表、framebuffer 移植配方、串口+SWD 双通道验收
- `references/boot-splash-and-swd.md` —— 启动动作条、多屏交接、短命启动帧的 SWD 取证

脚本：`scripts/fontchars.py`（字符集提取）、`scripts/gen_font.py`（字库生成）、
`scripts/check_font_coverage.py`（覆盖校验）、`scripts/decode_snap.py`（帧解码）、
`scripts/serial_capture.py`（串口取证）。
