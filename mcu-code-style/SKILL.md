---
name: mcu-code-style
description: 嵌入式 C 自研代码规范：第三方库边界、文件与命名、缩进与括号、文件级静态变量合并为结构体、按数量选对外接口粒度、固定宽度整数类型、禁堆/禁VLA内存管理、头文件 extern C、注释规范。适用于"静态变量怎么组织""变量怎么对外暴露""命名风格""括号风格""头文件怎么写""注释太长"等请求。
globs: ["*.c", "*.h"]
agent_created: true
---

# MCU C 代码规范（仅自研代码）

> **适用范围**：只约束本工程**自研代码**（`app/`、`bsp/`、`sys_startup/` 中自研部分）。
> `Drivers/`、`third_party/`、HAL/CMSIS、RTOS 与中间件（LVGL / LwIP / TinyUSB / FatFs），
> 以及 ST 提供的 `system_stm32h7xx.c` / `startup_*.s` / `stm32h7xx*.h` 等 CMSIS 文件，
> 一律不套用本规范——它们是外部代码，改了就失去可升级性。细则见 §0。

---

## §0 适用范围与第三方边界（最高优先级）

**本规范只约束自研代码。** 第三方包含：`Drivers/`、`third_party/`、HAL/CMSIS、RTOS 内核，
以及 LVGL / LwIP / TinyUSB / FatFs 等中间件、ST 提供的 CMSIS 文件（`system_stm32h7xx.c`、
`startup_*.s`、`stm32h7xx.h`、`stm32h743xx.h` 等）。

- ⚠️ **所有规则不适用于第三方库；第三方库有问题只能手动修改**，不要自动套用本规范去改它们。
- 定位到「问题出在第三方库」时，正确做法：
  1. 写清**现象**（复现步骤、原始日志/报错）；
  2. 给出**根因判断**与影响面（影响哪些功能、有无临时绕行）；
  3. 交由作者（本人）决定改法。
- 理由：第三方库的问题可能是有意设计、版本缺陷，或应经升级/配置项/上层绕行解决。
  **就地打补丁是最坏选项**——下次升级会被覆盖，且问题被藏起来。
- 例外：确有必须修改时，**先提出、等确认**，并把改动单独记录（便于升级时重放）。

---

## §1 文件与命名

| 项 | 约定 | 示例 |
|---|---|---|
| 文件名 | 统一小写 | `bsp_log.c` / `sd_app.h` |
| 目录名 | 统一小写，仅 `Drivers` 保留 STM 原大小写 | `app/` `bsp/` `sys_startup/`；`third_party/` `MDK-ARM/` `build/` 为上游/工具约定目录，保留其原大小写 |
| 变量 / 函数 | 只用小写蛇形（尽量） | `g_cdc`、`bsp_led_write` |
| 宏定义 `#define` | 大写（尽量） | `LINE_MAX`、`UART_TX_BUF_SIZE` |
| 枚举值 | 大写（尽量） | `LINK_MOUNTED`、`TUSB_SPEED_FULL` |
| 结构体 / 联合体**类型名** | 大写（尽量） | `CDC_STATE_T`、`LINK_STATE_T` |

- 前缀约定：文件级状态实例用 `g_`（global）；文件内静态用 `s_`（static）。
  合并进结构体后，成员上的 `s_` 前缀冗余，建议去掉（见 §3）。
- "尽量"含义：既有第三方 API / HAL 的命名（如 `HAL_UART_Init`、`GPIO_InitTypeDef`）
  不强制改写；**新写**的自研代码严格遵守本表。

---

## §2 缩进与括号

- **缩进**：1 个 tab 用 **4 个空格**替换；全文不使用真实 tab 字符（`\t`）。
- **开括号独占一行（Allman 风格）**，适用于：
  - 函数定义括号；
  - 局部块括号（`if` / `for` / `while` / `switch` / `do`）；
  - `} else {` 拆成三行（`}` / `else` / `{`），`} else if (...) {` 同理。
- **闭括号同样独占一行，且与对应的开括号同列**（Allman 两端对齐）。
  ⚠️ **单行体函数必须展开**：`fn(void){ stmt; }` 或 `bool sdcard_present(void){ return g; }`
  这类写法一律拆成：
  ```c
  bool sdcard_present(void)
  {
      return g;
  }
  ```
  不要保留"开括号同行、闭括号同行"的紧凑写法——这是最常见的遗漏点。
- **例外（不强制换行）**：
  - 类型定义括号：`struct` / `enum` / `union` 的 `{` 与关键字同行；
  - 初始化列表的 `= {` 不换行（数据表保持紧凑）。

```c
/* ❌ K&R：括号同行 */
static void cdc_task(void) {
    if (!tud_cdc_available()) return;
}

/* ✅ Allman：括号换行 */
static void cdc_task(void)
{
    if (!tud_cdc_available())
    {
        return;
    }
}
```

### 落地工具：`.clang-format`（自动化对齐，避免手改）

本规范的缩进/括号是**机械性**规则，手写易漏。在仓库根放一份 `.clang-format`，
用 `clang-format -i` 一键对齐（CI 或提交前跑）。注意 clang-format **23.x** 把
`AllowShortIfStatementsOnASingleLine` / `AllowShortLoopsOnASingleLine` /
`AllowShortBlocksOnASingleLine` 的 `Never` 改成了**布尔值**（`false`），写 `Never` 会报错。

```yaml
---
Language: Cpp
BasedOnStyle: LLVM
IndentWidth: 4
TabWidth: 4
UseTab: Never
ColumnLimit: 0            # 不折行，保留既有手工换行，最小化 diff
BreakBeforeBraces: Custom
BraceWrapping:
  AfterFunction: true
  AfterControlStatement: true   # if/for/while 开括号独立成行
  AfterEnum: false              # enum { 与关键字同行（§2 例外）
  AfterStruct: false            # struct { 与关键字同行（§2 例外）
  AfterUnion: false
  BeforeElse: true              # } else { -> } / else / {
AllowShortFunctionsOnASingleLine: None
AllowShortIfStatementsOnASingleLine: false
AllowShortLoopsOnASingleLine: false
AllowShortBlocksOnASingleLine: false
SpaceBeforeParens: ControlStatements
PointerAlignment: Right
SortIncludes: false
IncludeBlocks: Preserve
...
```

> 用前先 `clang-format --version` 确认大版本；本配置在 clang-format 23 验证通过。
> 第三方目录（Drivers/third_party、ST 组件、CMSIS/启动文件）**不要**纳入格式化。

---

## §3 文件级静态变量：合并成结构体

**规则**：同一文件内的多个 `static` 变量，若属于**同一件事**，合并为一个结构体实例，
不再平铺成 N 个独立 `static`。收益是「后期统一管理」：初始化、复位、快照、调试观察
都只需点名一处，新增字段也不会漏改。

```c
/* ❌ 平铺：复位/快照要逐个点名，新增一个就漏一处 */
static volatile link_state_t s_link = LINK_UNMOUNTED;
static uint32_t s_rx_bytes = 0;
static uint32_t s_tx_bytes = 0;
static uint32_t s_lines    = 0;
static bool     s_heartbeat = false;

/* ✅ 聚合：一次初始化、一次复位、一次观察 */
typedef struct
{
    volatile link_state_t link;
    uint32_t rx_bytes;
    uint32_t tx_bytes;
    uint32_t lines;
    bool     heartbeat;
} link_info_t;

static link_info_t g_link_info = {0};   /* 显式 = {0}，不依赖隐式零初始化 */
```

**命名**：结构体按**所在文件 / 所管功能**命名（`link_info_t`、`camera_state_t`、`ui_state_t`），
类型名用大写（见 §1）。

**⚠️ 边界——合并的前提是「同一件事」**：
禁止为了省事把不相干的状态塞进同一个结构体。
一个文件里若有「链路统计 / UI 状态 / 标定参数」三件事，那就是**三个**结构体。

**判据**：这个结构体的字段，是否会被**同一段代码一起初始化 / 一起复位 / 一起打印**？
答不上来的字段，就不属于这个结构体。

**连带要求**：

- **`volatile` 限定留在成员上**（被 ISR 写的那个字段），不要加到整个结构体。
- **成员命名**：包进结构体后，成员上的 `s_` 前缀已经冗余（`g_link_info.s_link`
  读起来是重复的）。建议去掉，直接用 `link` / `rx_bytes`；若要保留以便全文 grep，
  则**全工程统一**，不要两种混用。

---

## §4 其它文件访问结构体：按「要暴露几个」选粒度

| 需要暴露的量 | 接口形式 | 理由 |
|---|---|---|
| **少量**（1~2 个） | 对**单个变量**暴露读 / 写接口 | 语义明确，可在 setter 内加校验与副作用 |
| **多量**（≥3 个，或需整体快照） | 对**结构体**暴露对外指针接口 | 免去 N 个访问器与逐字段值拷贝 |

```c
/* 少量：单变量接口 */
link_state_t app_get_link_state(void)            { return g_link_info.link; }
void         app_set_link_state(link_state_t st) { g_link_info.link = st; }

/* 多量：结构体指针接口（只读场景） */
const link_info_t *app_get_link_info(void)       { return &g_link_info; }
```

**两条硬要求**：

1. **对外接口不能带 `static`**。`static` 是「仅本文件可见」，加了它别的文件根本链不到——
   在本文件内调用一切正常，很容易误以为已经暴露，换到别的文件就是 `undefined reference`。
   （对外接口同时要在头文件里声明。）
2. **只读就返回 `const` 指针**。返回 `link_info_t *` 等于把写权限一并放出去，
   调用方可绕过 setter 直接改，封装形同虚设。
   确有外部写入需求时才返回非 const，并在注释里写明「谁在写」。
   > 读多写少的场景，默认选 **`const` 指针 + 单个 setter**。

**为什么不用 `extern` 直接共享变量**：跨文件裸变量会带来「初始化顺序不确定」
与「谁都能改」两个问题；指针接口把可见性收敛到一处，也便于日后改成加锁访问。

---

## §5 类型：用固定宽度整数类型

- 用 `uint8_t / int8_t / uint16_t / int16_t / uint32_t / int32_t / ...`
  取代 `char` / `short` / `int` / `long` 等平台相关宽度类型，避免跨平台宽度歧义
  （尤其 `char` 是否带符号、`long` 宽度因 ILP32/LP64 而异）。
- **例外**：真正作为 C 字符串（传给 `strlen` / `strcmp` / `printf("%s")` 的缓冲区和参数）
  保留 `char`；纯整数语义的 `char` / `short` 改成对应 stdint 类型。
- 需要 `#include <stdint.h>`；布尔用 `#include <stdbool.h>` 的 `bool` / `true` / `false`。

```c
/* ❌ 平台相关宽度，char 符号性未定义 */
char     c   = buf[i];
short    s   = calc();
uint32_t len = strlen(s);   /* strlen 需要 char*，这里保留 char */

/* ✅ 整数语义用 stdint；字符串语义保留 char */
uint8_t  c   = buf[i];
int16_t  s   = calc();
```

---

## §6 内存：不用堆、不用变长数组

- **不使用变长数组（VLA）**：如 `int buf[n];` 且 `n` 非编译期常量（栈上长度运行期决定，
  在中断/小栈环境极危险）。
- **不使用 `malloc` / `free`**（以及 `alloca`）。
- 有动态内存需求时：
  - **FreeRTOS 环境**：用 `pvPortMalloc` / `vPortFree`；
  - **非 RTOS / 裸机环境**：自定义静态内存池或块分配器，禁止裸 `malloc`。
- 优先使用**编译期确定大小**的静态缓冲 / 栈缓冲；确需运行期可变长度时，
  用固定上限环形缓冲或预分配池。

```c
/* ❌ 裸 malloc / VLA */
uint8_t *p = malloc(n);
int      buf[n];

/* ✅ 裸机：静态池；FreeRTOS：pvPortMalloc */
static uint8_t s_pool[POOL_MAX];
uint8_t *p = pvPortMalloc(n);   /* FreeRTOS only */
```

---

## §7 头文件：C/C++ 混合编程接口

所有自研 C 头文件用带 `#ifdef __cplusplus` 检测的 `extern "C"` 包裹，
预留 C/C++ 混合编译（被 C++ 源文件 `#include` 时不会因 name mangling 导致链接失败）。

```c
#ifndef BSP_LED_H
#define BSP_LED_H

#ifdef __cplusplus
extern "C" {
#endif

void bsp_led_write(bool on);
bool bsp_led_read(void);

#ifdef __cplusplus
}
#endif

#endif /* BSP_LED_H */
```

- `#include` 防护用 `#ifndef XXX_H / #define XXX_H / #endif`（或 `#pragma once`）。
- 仅声明、不定义；定义放 `.c`。`extern "C"` 只包裹声明，不影响宏与类型定义。

---

## §8 注释规范

目标：注释是摘要不是教材。读代码不需要跳读注释；要深挖时有落档处。

### 四条规则

1. **变量**：在**声明处**注释；使用处默认不注释。
   例外：使用处有特殊公式推导或判断条件约束（如定点换算、边界钳位、
   依赖顺序）才注释，且 **≤30 字节、一行**。
2. **版本更新**：不再适用的旧注释**直接删除或改写**。
   禁止「旧注释保留 + 后面追加新注释」——那会让注释单调膨胀、且新旧并存误导。
3. **信息量大且关键**（坑、时序、推导、真机取证）→ 写入项目
   `docs/annotation.md` 承接表（或既有硬件/设计文档如 hw.md 的 §号），
   代码内只留一行摘要 + 指针（`/* ⚠️ 见 docs/annotation.md 表 X */`）。
4. 第三方目录不做注释处理（见 §0）。

### 行文基准

- 单行注释 ≤30 字节（约 10~15 个汉字），一行说一件事。
- 文件头 2~4 行（文件 + 一句话职责），函数 doc 1~2 行。
- 多个 ⚠️ 警告并列时：每条压成一行，详情编号落档，不整段复述。

### 落地手法（防翻车）

- **同文件多处改动必须串行发**：并行/批量编辑同一文件会互相覆盖丢改动
  （症状：只有每批最后一个编辑存活、文件呈新旧混合态）。
- 大文件整文件重写前，先用脚本**剥注释求 token 哈希**存基线，
  重写后比对哈希证明「只动了注释、没动代码」：
  删 `/*...*/`（re.S）与 `//...`，折叠空白，sha1。
- 版本记录（changelog/版本史）写在文档里，**不写进代码注释**；
  代码注释只描述「现在是什么」，不描述「从 vN.x 改成了什么」。

---

## §9 检查清单（收尾自检）

- [ ] **第三方 / Drivers / CMSIS 文件未被改动**；第三方问题只上报、未自行修改
- [ ] 文件名全小写；**目录名全小写（仅 `Drivers` 保留 STM 原大小写）**；变量/函数小写；宏/枚举值/结构体类型名大写
- [ ] 缩进为 4 空格、无真实 tab；函数与局部块**开/闭括号均独占一行且同列**（含 `} else {` 拆三行、单行体函数 `fn(void){ s; }` 已展开为三行）
- [ ] 同文件同性质的 `static` 变量已合并为一个结构体，且结构体只装「同一件事」
- [ ] 结构体实例显式 `= {0}` 初始化；`volatile` 限定落在成员上
- [ ] 对外接口**未加 `static`**；只读接口返回 `const` 指针
- [ ] 接口粒度匹配：少量用单变量接口，多量用结构体指针接口
- [ ] 整型语义用 `uint8_t/int16_t/...`；C 字符串保留 `char`
- [ ] 无 `malloc/free/alloca`、无 VLA；动态内存走 `pvPortMalloc/vPortFree` 或自定义池
- [ ] 自研头文件均有 `extern "C"` 守卫与 include 防护
- [ ] 声明处有注释、使用处无冗余注释；使用处注释 ≤30 字节一行
- [ ] 无「新注释叠在旧注释后面」的追加痕迹
- [ ] `>30 字节` 的背景都有落档（`docs/annotation.md` 或 hw 类文档）

> 相关：`mcu-cpp-development`（C++ 侧的同类约定）、`stm32-build-and-scaffold`（工程骨架）、
> `mcu-logging`（日志模块自身的静态状态组织）。

---

## §10 更新与同步（强制 · 凡改本 skill 必做）

**本 skill（以及任何系统 skills `~/.workbuddy/skills/*/SKILL.md`）被修改后，
"规则写入"的收尾步骤必须同步完成，否则视为未完成：**

1. **改权威副本**：编辑 `~/.workbuddy/skills/mcu-code-style/SKILL.md`
   （全局 `~/.workbuddy/skills/` 是**唯一权威副本**，所有编辑都在此做，不在别处改）。
2. **同步到 EmbedSkills 仓库**（用户要求的"系统 skills 更新触发 EmbedSkills 同步"）：
   `cp ~/.workbuddy/skills/mcu-code-style/SKILL.md /d/user_project/git/EmbedSkills/mcu-code-style/SKILL.md`
3. **在 EmbedSkills 本地提交（不 push）**：
   `cd /d/user_project/git/EmbedSkills && git add mcu-code-style/SKILL.md && git commit`
   push 由用户自己处理（git push 不归我管）。

- ⚠️ **`support_tools/sync_skills.sh` 覆盖不到本 skill**：该脚本只纳管 18 个 MCU 域 skill，
  同步方向是 `全局 skills ⇄ 工程 .workbuddy/skills/ 镜像`，白名单里没有 `mcu-code-style`；
  本 skill 走上面的 **EmbedSkills 直接 cp + commit** 流程，不要误用该脚本。
- ✅ 验证：同步后 `diff -q` 两侧 SKILL.md 应一致。
- 两个仓库（EmbedSkills / 各业务工程）均**只本地 commit、不 push**。
