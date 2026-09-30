# 移植 STM32 工程到 Keil MDK-ARM（UV4 命令行构建）

适用场景：项目主体是 CMake + arm-none-eabi-gcc，但另需一套能在 Keil μVision 打开、
或用 `UV4.exe -b` 做 CI/命令行构建的工程。

核心矛盾：GCC/newlib 工程里有些文件与链接符号是工具链专用的，直接塞进 Keil 会编不过——
**正确做法是「排除」而非「改造」**。唯一的反例是半主机抑制垫片，它必须保留。

## 一、前置确认（动手前必查）

1. **UV4 路径**：Keil 安装目录下的 `UV4/UV4.exe`（默认安装目录名常见为 `Keil_v5`）。
   不要用 `UV4 -h`——它是 GUI 程序，会弹界面卡住。
2. **ARMCLANG 版本**：`<Keil>/ARM/ARMCLANG/bin/armclang.exe --version`。
   把 `pCCUsed=6140000::V6.14::ARMCLANG` 与 `uAC6=1` 写进 uvprojx，版本号须与实际安装一致。
3. **DFP 器件包**：按芯片系列装对应 DFP（H7 为 `Keil.STM32H7xx_DFP.<版本>`）。
   新版 Arm Pack 可能装在 `%LOCALAPPDATA%\Arm\Packs\Keil\...`，不在 `<Keil>/ARM/PACK`。
   uvprojx 里 `Device` / `PackID` 必须与已安装版本匹配，否则设备解析失败。
4. **启动文件语法**：确认 `sys_startup/arm/startup_stm32<系列>xx.s` 是 **MDK/Keil 语法**
   （`AREA` / `DCD` / `EXPORT __initial_sp` / `__heap_base` / `__heap_limit`），
   不是 GCC 的 `.word/.section`。Keil 的堆管理直接用启动文件导出的堆符号。
5. **⚠️ 生成 uvprojx 时禁止加入 `syscalls.c`**（任何路径下的 `Core/Src/syscalls.c` 等）。
   它是 GCC/newlib 专用垫片（`_sbrk` / `_write` / `__io_putchar`），ARMCLANG 自带堆管理，
   且它引用 POSIX 头 `<sys/stat.h>`，塞进 Keil 必报 `_sbrk 未定义` / 头文件找不到。
   **一律排除，不改写该文件。**
6. **⚠️⚠️ 半主机抑制垫片必须保留，绝不能删**（与第 5 条方向相反，极易搞错）。
   它是 Keil 工程的必需件，职责是抑制 ARMCLANG 的半主机实现：

   ```c
   #if defined(__CC_ARM)
   #pragma import(__use_no_semihosting)      /* ARMCC(AC5) */
   struct __FILE { int handle; };
   #else
   __asm(".global __use_no_semihosting");     /* ARMCLANG(AC6) */
   __asm(".global __ARM_use_no_argv");
   #endif
   FILE __stdout;
   void _sys_exit(int x) { x = x; }
   void _ttywrch(int ch) { ch = ch; }
   ```

   文件放在 MDK 工程目录下（文件名可自定，例如 `MDK-ARM/mdk_target.c`）。

   **删掉后的症状**：编译链接**可能仍然通过**（若当前无裸 `printf`，符号被 `--gc-sections` 丢弃），
   但一旦代码里出现 `printf` / `fprintf` / `scanf` / `fopen` 等**任何会走 C 库 I/O 的调用**，
   ARMCLANG 就会链入半主机实现 → 运行到 `_sys_open` / `_sys_write` 时执行 **`BKPT` 指令**
   → 停机在调试器里（或 HardFault），表现为「串口无输出 / 程序莫名停住」。
   **这是延迟暴露的坑，不是编译期报错**，所以最容易被误删。

   > **与应用层日志通道的关系**：应用层日志（`PRINT_LOG` → 自己的 TX 环，见
   > `mcu-logging`）**不能替代**半主机抑制——两者职责不同，**必须共存**。
   > 应用层日志里的 `_write()` 重定向通常只在 `#if defined(__GNUC__) && !defined(__ARMCC_VERSION)`
   > 下生效，MDK 侧走不到那里；MDK 侧靠的是「应用层不直接调 `printf`」+「半主机抑制垫片兜底」双保险。

   **验证（每条必查）**：反汇编确认无半主机 `BKPT`：

   ```bash
   fromelf --text -s Objects/<target>.axf | grep -E "__use_no_semihosting|_sys_exit"
   fromelf --text -c Objects/<target>.axf | grep -cE "[[:space:]]BKPT[[:space:]]"   # 期望 0
   ```

## 二、从 CMake 清点真实源集（别信旧的 uvprojx）

旧 uvprojx 经常指向另一套应用（FatFs / MSC / CDC 等），直接重写更稳：

```bash
# 看 CMake 里都编了哪些 .c，以及 IncludePath / 宏定义
grep -nE "add_executable|target_include_directories|target_compile_definitions|HSE_VALUE|CFG_" CMakeLists.txt
ls Core/Src bsp Drivers/STM32<系列>xx_HAL_Driver/Src third_party/<lib>/src
```

据此重组 uvprojx 的 Groups / Files。

强约束（生成 MDK-ARM 工程必守）：
- **① 不要添加 `syscalls.c`**。若 CMake 侧存在（或用 `file(GLOB Core/Src/*.c)` 收集到的），
  清点源集时必须显式剔除，绝不写进 uvprojx 的 `<Files>`。
- **② 必须保留半主机抑制垫片**（见第一节第 6 条），删了会导致延迟暴露的 `BKPT` 死机。
- **③ HAL 侧不要整包导入**（见第四节·A）。

## 三、分散加载文件（`<target>.sct`）

镜像 GCC 的 `*.ld`。示例：把摄像头帧缓冲 `.framebuffer` 钉在 **AXI SRAM 0x24000000**
（DCMI DMA 只能访问该域；DTCM 放 `.data/.bss/heap/stack`，SRAM_D2/D3 兜底溢出）：

```
LR_IROM1 0x08000000 0x00200000
{
  ER_IROM1 0x08000000 0x00200000  { *.o (RESET, +First) * (InRoot$$Sections) .ANY (+RO) }
  RW_IRAM2 0x24000000 0x00080000  { *.o (.framebuffer) *.o (.ram_d1) }   /* AXI: 帧缓冲 */
  RW_IRAM1 0x20000000 0x00020000  { .ANY (+RW +ZI) }                     /* DTCM: 快内存 */
  RW_IRAM3 0x30000000 0x00048000  { .ANY (+RW +ZI) }                     /* SRAM_D2 */
  RW_IRAM4 0x38000000 0x00010000  { .ANY (+RW +ZI) }                     /* SRAM_D3 */
}
```

- 各段基址/长度按**实际芯片**的存储域填，不要照搬示例地址。
- 不要试图用 scatter 的 `EXPORT _end/_estack/_Min_Stack_Size` 给 newlib `_sbrk`——
  ARMCLANG 不认这些符号，也根本不需要（它用自己的堆）。**排除 `syscalls.c` 才是正解。**
- 但**半主机抑制不能省**：`syscalls.c` 是「别加进去」，抑制垫片是「必须留在里面」，
  两者方向相反。

### 三·A、段「加载地址 ≠ 运行地址」：armlink 没有嵌套 load region

典型需求（双 Bank Flash 的擦写引擎、从 RAM 执行的 bootloader 跳转引擎）：
代码段**烧在 Flash**，运行时**拷到 AXI SRAM 执行**。GCC 侧靠 `>SRAM1 AT> FLASH` 一行搞定，
armlink **必须拆成两个平级顶层 load region**：

```
LR_IROM1 0x08000000 0x0001E000
{
  ER_IROM1 0x08000000 0x0001E000
  {
    *.o (RESET, +First)
    *(InRoot$$Sections)
    .ANY (+RO)
  }

  RW_IRAM1 0x24001000 UNINIT
  {
    *( +RW, +ZI )                 /* 逗号！+RW +ZI 是语法错 */
  }

  RW_STACK 0x20000000 UNINIT { *.o (STACK) }
  RW_HEAP  0x20000400 UNINIT { *.o (HEAP) }
}

/* 独立顶层 load region —— 不能写成 UPGRADE_RAM LR_IROM1 { ... } */
LR_UPGRADE 0x0801E000 0x00002000
{
  UPGRADE_RAM 0x24000000 0x00002000
  {
    *.o (.upgrade_ram)
    *.o (.upgrade_ram*)
  }
}
```

**踩坑记录（10 个 error 的连锁）**：

| 写法 | 报错 |
|---|---|
| `UPGRADE_RAM_LOAD LR_IROM1 { ... }`（嵌套） | `L6630E: Invalid token start` + `L6226E: Missing base address for region UPGRADE_RAM_LOAD` + `L6292E: Ignoring unknown attribute 'LR_IROM1'` |
| `*( +RW +ZI )` | `L6630E` / `L6628E: Expected '{', found ',...'` |
| `*(UPGRADE_RAM)`（无点） | `L6231E: Missing module selector` |
| `UNINIT` 挂 load region | `L6324W: Ignoring UNINIT attribute specified for Load region` |

**定位手法**：直接跑 `armlink.exe --scatter=<file> --info=sizes`（不经 IDE），
再在临时目录里做最小变体二分——比反复 UV4 全量构建快得多。

**区域符号名来自「执行域」标签**：执行域叫 `UPGRADE_RAM` → `Image$$UPGRADE_RAM$$Base` /
`$$Limit` / `Load$$UPGRADE_RAM$$Base`。若执行域写成 `ER_UPGRADE` 就得引用
`Image$$ER_UPGRADE$$Base` —— 改名后**必须回头核对 C 侧 `extern` 声明**，否则 `L6218E`。

**C 侧跨工具链写法**（不进任何链接选项，纯 scatter + 预处理）：

```c
#if defined(__ARMCC_VERSION)
extern uint8_t Image$$UPGRADE_RAM$$Base[];
extern uint8_t Image$$UPGRADE_RAM$$Limit[];
extern uint8_t Load$$UPGRADE_RAM$$Base[];
#define RUN_START  ((uint32_t)(uintptr_t)Image$$UPGRADE_RAM$$Base)
#define RUN_END    ((uint32_t)(uintptr_t)Image$$UPGRADE_RAM$$Limit)
#define LOAD_START ((uint32_t)(uintptr_t)Load$$UPGRADE_RAM$$Base)
#else
extern uint8_t _supgrade_ram, _eupgrade_ram, _supgrade_ram_load;
#define RUN_START  ((uint32_t)(uintptr_t)&_supgrade_ram)
#define RUN_END    ((uint32_t)(uintptr_t)&_eupgrade_ram)
#define LOAD_START ((uint32_t)(uintptr_t)&_supgrade_ram_load)
#endif

memcpy((void *)RUN_START, (const void *)LOAD_START, RUN_END - RUN_START);
__DSB(); __ISB();   /* 拷贝后立刻生效，再调用进去 */
```

> 先试过 `--predefine=-D_supgrade_ram=Image$$UPGRADE_RAM$$Base`（含 `$$`→`\$` 各种转义），
> **全部无效**，符号仍 undefined。改走上面的纯 C 分支后**不需要任何链接选项**。

**多 load region ⇒ After-Build 必须用 `--bincombined`**：

```bat
fromelf --bin           --output Objects\app.bin !L   :: 产出「目录」！每个 region 一个文件
fromelf --bincombined   --output Objects\app.bin !L   :: 单文件可烧录镜像 ✔
```

判据：`ls Objects/app.bin` 若是个目录（内含 `ER_IROM1` / `UPGRADE_RAM` 等分片），
就是用了 `--bin`。

**验收（ELF 级，无需真机）**：

```bash
arm-none-eabi-readelf -S Objects/app.axf | grep -A1 UPGRADE_RAM   # Address 应为 RAM 地址
fromelf --text -s Objects/app.axf | grep -E "Image\\\$\\\$UPGRADE_RAM|Load\\\$\\\$UPGRADE_RAM"
# Load$$UPGRADE_RAM$$Base 应落在 Flash loader 区，Image$$UPGRADE_RAM$$Base 应是 RAM 地址
```

## 四、重写 uvprojx（关键字段）

- `<TargetName>` / `<Device>STM32<型号>xx</Device>` / `<PackID>Keil.STM32<系列>xx_DFP.<版本></PackID>`
- `<pCCUsed>6140000::V6.14::ARMCLANG</pCCUsed>`、`<uAC6>1</uAC6>`
- **Thumb 必开**：`<Cads><uThumb>1</uThumb>` 且 `<Aads><thumb>1</thumb>`。
  旧工程若误设 `uThumb=0` 会生成非法 ARM 态代码（Cortex-M 只认 Thumb）。
- **C 语言级别**：`<Cads>` 里补 `<uC99>1</uC99><uGnu>1</uGnu><v6Lang>5</v6Lang><v6LangP>5</v6LangP>`。
  源码用了 `_Static_assert`（C11）或 C99 `[static N]` 数组参数时必须给到 C99/GNU 变体，
  否则报的是**看不懂的语法错**（如 `expected expression`）。本项目实测该组合可编过这两者。
- **IncludePath**（相对路径，随工程移动）：用户头目录 + HAL `Inc`（含 `Inc/Legacy`）
  + `Drivers/CMSIS/Include` + `sys_startup` + 各 `third_party/<lib>/src`。
- **Define**（沿用 CMake，补齐缺失项）：芯片宏（`STM32<型号>xx`）、`USE_HAL_DRIVER`、
  `HSE_VALUE=<按板载晶振>`、供电方式宏、以及各第三方库的 `CFG_*`。
- **MiscControls（C）**：`-Wno-unused-parameter -Wno-sign-compare`
  ⚠️ **单横杠**。ARMCLANG 不接受 GCC 的 `--Wno-...`（报 `unknown option`）。
- **ScatterFile**：`<target>.sct`，并勾 `<useFile>1</useFile>`。
- **After Build**：`fromelf --bin !L --output Objects\<target>.bin`。
- **Groups/Files**：Application/Startup（startup `.s` + `system_<系列>xx.c`）、
  Application/User/Core（main 等，**务必含半主机抑制垫片**）、
  Drivers/…_HAL_Driver（**按需 HAL `.c`**）、BSP/`<模块>`、Middlewares/`<lib>`。
  **`syscalls.c` 不在此列表；抑制垫片必须在此列表。**
- **特性开关 / 可选源文件**（如调试探针，整份代码受 `#ifdef CAM_DIAGNOSTICS` 包裹）：
  在 uvprojx 里**无条件列入**（让源列表与 CMake 的 `option()` 条件源集对齐），整份代码
  用宏包裹。默认 `<Define>` 不定义该宏 → 编出**零符号空 TU**（实测 ARMCLANG 对空 TU 零
  警告，`.o` 仅数百字节，`nm` 无符号）。启用时只在 `C/C++ (AC6) → Preprocessor Symbols →
  Define` 加宏，**不动源文件列表**。⚠️ 别为"对齐"把该源从 uvprojx 删掉——那样开关打开时
  还得同时改两处（源列表 + Define），容易漏。

## 五、UV4 命令行构建与日志解析

```bat
"<Keil>\UV4\UV4.exe" -b -j0 -t <target> -x "<工程>\MDK-ARM\<target>.uvprojx" -o "<工程>\MDK-ARM\build_log.htm"
```

- `-b` 批构建；`-j0` 不限并发；`-t` 指定 target；`-o` 写 HTML 日志。
- **stdout 不一定回显**，判断成败靠日志末行：
  `"Objects\<target>.axf" - 0 Error(s), 0 Warning(s).`
- **⚠️ 退出码不可信**：UV4 是 GUI 子系统程序，从 Git Bash / CI 等非控制台环境启动会
  **立即返回退出码 0 并在后台异步构建**（UV4 文档的"0=成功 / 2=错误"只在真正的控制台
  前台运行时成立）。实测：命令 0.1 s 返回 0、`-o` 指定的日志**根本没生成**，而
  `Objects/*.o`、`.axf` 的 mtime 在两秒后才更新 → 构建其实成功，但同样的机制会把真实
  失败也谎报成 0。**可靠判据 = 日志末行 + `Objects/<target>.axf` 的 mtime 是否更新**；
  找不到 `-o` 日志时，UV4 的默认构建日志落在 `MDK-ARM/Objects/<target>.build_log.htm`。
- 尺寸：`fromelf --info=totals Objects\<target>.axf` → `Total ROM Size`（≈ `.bin` 大小）、
  `Total RW Size`（RW+ZI，含 AXI 帧缓冲）。
- 产物：`Objects/<target>.axf` / `.hex` / `.bin`。

## 六、常见坑（按出现频率排序）

| 现象 | 根因 | 修法 |
|------|------|------|
| `error: unknown option '--Wno-...'` | ARMCLANG 用单横杠 | 改 `-Wno-...` |
| `_sbrk` / `_end` / `_estack` 未定义 | 把 GCC 的 `syscalls.c` 加进了 Keil | 从工程移除 `syscalls.c`，ARMCLANG 自带堆 |
| `<sys/stat.h>` / `<sys/types.h> not found` | 同上（`syscalls.c` 引用 POSIX 头） | 移除即可，勿改文件 |
| 生成非法 ARM 态指令 | `uThumb=0` | 设 `uThumb=1`、`thumb=1` |
| 分散加载 `EXPORT` 不生效 | ARMCLANG 不认 `_end` 等 | 别 EXPORT，排除 `syscalls.c` |
| **烧录后串口无输出 / 程序停在 `BKPT`（调试器里看不出，编译链接却全过）** | **误删了半主机抑制垫片，半主机未抑制**；一旦有裸 `printf` 即链入半主机 | 恢复垫片（`__use_no_semihosting` + `_sys_exit`/`_ttywrch`），并用 `fromelf --text -c` 确认 `BKPT` 计数为 0 |
| `UV4` 卡住不返回 | 误加 `-h` 或弹 GUI | 只用 `-b` 批模式，日志走 `-o` |
| **UV4 秒退且退出码 0、却找不到日志（构建其实还在后台跑）** | GUI 程序脱离控制台（Git Bash / CI 启动） | 别信退出码；判据改用日志末行 + `Objects/*.axf` mtime，默认日志在 `Objects/<target>.build_log.htm` |
| 设备解析失败 | DFP 版本/路径不对 | 装对 DFP 版本，确认 `PackID` |
| `L6218E: Undefined symbol tusb_time_millis_api (referred from tusb.o)` | `CFG_TUSB_OS=OPT_OS_NONE` 下 TinyUSB 要求应用实现（见六·D） | 在 `bsp/` 里定义 `uint32_t tusb_time_millis_api(void){ return HAL_GetTick(); }` |
| `L6218E: Undefined symbol Image$$XXX$$Base` | 区域符号名取自**执行域**标签，与 C 侧 `extern` 名不一致 | 用 `fromelf --text -s` 查真实符号名，或把执行域改名对齐 |
| `L6630E` / `L6226E` / `L6292E`（嵌套 load region） | armlink 不支持 `ER LR_IROM1 { }` 写法 | 改平级顶层 load region（见三·A） |
| `L6231E: Missing module selector` | 段选择器少了点 | `*(SEC)` → `*.o (.sec)` |
| `fromelf --bin` 产出一个目录 | 存在多个非连续 load region | 改用 `--bincombined` |
| 编译链接时间过长、Flash 占用虚高、无用符号告警 | 整包导入了 HAL 全部 `.c` | 按需引入 HAL 源，见下节 A |

### 六·A、HAL 库按需引入（Keil 侧写法）

Keil 侧的特殊性在于：**`.` 文件全量入组会真的把代码链进去**（ARMCLANG 默认保留，
不像 GCC 有 `--gc-sections` 兜底）→ Flash 占用显著虚高，还会引入无关模块的编译错误/告警。

做法与 CMake 侧完全一致：按 `HAL_XXX_` 反查所需模块 → 只把这些 `.c`（含必需 `_ex.c`）
列进 uvprojx 的 HAL 组。任何工程都必须包含 4 个基础件
（`hal.c` / `hal_cortex.c` / `hal_rcc.c` / `hal_rcc_ex.c`）再加 `hal_gpio.c`；
`stm32<系列>xx_hal_msp.c` 与 `stm32<系列>xx_it.c` 属用户 `Core/Src`，照常加入。

⚠️ 引入**新外设**时，必须**两侧同步**补进 CMake 源集与 uvprojx HAL 组，否则链接报
`undefined reference to HAL_XXX_Init`。include 路径仍为 HAL `Inc`（+ `Inc/Legacy`），不变。

**验收红线**：HAL 入组 `.c` 数量应为**个位数~十几个**（按实际外设），不应是目录全量
（H7 约 80+）；且 uvprojx 中 HAL 组文件数应等于 CMake 侧 HAL 源条数。

### 六·B、第三方库里的 newlib 专有头（移植 ARMCLANG 的第二大障碍）

现象：某个**第三方库头文件**（本项目是 `third_party/ssd1306/ssd1306.h`）里
`#include <_ansi.h>`，报 `'_ansi.h' file not found`，并连带 `_BEGIN_STD_C` /
`_END_STD_C` 未定义 —— **一个根因 4 个 error**，日志里看起来像"到处都是问题"。
`_ansi.h` 是 **newlib 专有**，ARMCLANG 没有。

判据：这类文件**不是可排除项**（它是产品的真依赖），必须改造。先确认用法范围：

```bash
grep -rn "_ansi\.h\|_BEGIN_STD_C\|_END_STD_C\|_U_\|_NOTHROW" third_party/
```

上游用这一对宏，通常只是要一个 `extern "C"` 守卫。**就地展开**，两条工具链行为等价：

```c
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* ... 声明 ... */
#ifdef __cplusplus
}
#endif
```

改完必须**跑一次 GCC 双构回归**确认零差异 —— "为适配 A 工具链而改共用头"最容易在
B 工具链上引入静默行为变化。

⚠️ 与 `syscalls.c` 的区别要分清：那是**工程文件**（排除即可）；这是**第三方库的头**
（排除不了，只能改）。同类需警惕的 newlib/POSIX 头：`<sys/stat.h>` `<sys/types.h>`
`<unistd.h>` `<reent.h>`。

### 六·C、栈/堆预算：两条工具链的默认值几乎必然不一致

GCC 的 `.ld` 与 Keil 的 `startup_<part>.s` **各自保存一份** `Stack_Size` / `Heap_Size`，
移植时极易只改一边。本项目实测差异：

| | GCC（`.ld`） | Keil（`arm/startup_*.s`） | 处置 |
|---|---|---|---|
| Stack | 2 KB | **1 KB** | 对齐 → 2 KB |
| Heap | 512 B | **0 B** | 对齐 → 512 B |

⇒ 移植后**逐项核对这两个数**：

```bash
grep -nE "Stack_Size|Heap_Size" sys_startup/arm/*.s sys_startup/*.ld
```

不一致就以 GCC 侧为准改 Keil 侧。栈偏小只在"栈上格式化"类代码（`snprintf` + 栈缓冲，
如本项目 `bsp_uart_printf`）里暴露，属**偶发、难查**的一类问题。

判据：Keil 的 `ZI-data` 增量应恰好等于两处差值之和（本项目 +1536 = +1024 + 512），
且 `.bin` 头部第 1 个字（初始 SP）随之抬升。

### 六·D、无 `--gc-sections` 的第二重后果：库的「应用弱钩子」必须真实现

Keil 不只把「入了组的 `.c`」全量链进去，还**不做 GCP 摘除**。所以第三方库中那些
「声明由应用提供」的弱钩子，在 GCC 下可能从未暴露，在 Keil 下直接 `L6218E`。

实测案例（TinyUSB，`CFG_TUSB_OS=OPT_OS_NONE`）：

```c
/* third_party/tinyusb/src/tusb.c —— 被 tusb_time_delay_ms_api() 引用 */
uint32_t tusb_time_millis_api(void);   /* "implemented by the application" */
```

- **GCC 侧**：`tusb_time_delay_ms_api` 是独立 section `.text.tusb_time_delay_ms_api`，
      `--gc-sections` 把它整段摘掉 → 该符号**在 GCC 的 ELF 和 map 里都不存在**，
      所以从没报错。
- **Keil 侧**：报 `Undefined symbol tusb_time_millis_api (referred from tusb.o)`。

修法：在 `bsp/`（板级）里真实现，不放 third_party：

```c
/* bsp/usb_board.c */
uint32_t tusb_time_millis_api(void) { return HAL_GetTick(); }
```

⇒ **通用判据**：Keil 首次链接第三方库时，凡 `referred from <lib>.o` 的 undefined 符号，
先怀疑「该库文档里写着由 application/port 提供」的钩子，而不是自己的代码写错了。
同族还有 `CFG_TUSB_OS` 相关的 `osal_*`、以及 RTOS 的 `vApplicationIdleHook` 等。

### 六·E、镜像里的 `BKPT`：先分辨来源，别一律当半主机

TinyUSB 的 `TU_BREAKPOINT()`（`src/common/tusb_verify.h`）会生成一段
**读 `CoreDebug->DHCSR` 的守卫**，只有挂着调试器时才真的执行 `BKPT #0`：

```
f64e50f0    mov.w  r0, #0xedf0
f2ce0000    movt   r0, #0xe000
6800        ldr    r0, [r0]      ; CoreDebug->DHCSR
07c0        lsls   r0, r0, #31
d000        beq    +0
be00        bkpt   #0
```

一个用到 TinyUSB 的镜像里这类 `BKPT` 有几十个（本项目 61 个）是**正常的**。

**判据（两条都要查）**：

```bash
fromelf --text -c Objects/app.axf | grep -cE "[[:space:]]BKPT[[:space:]]"   # 数量可能非 0
fromelf --text -c Objects/app.axf | grep -c "SVC.*0xab"                    # 半主机：必须 0
```

半主机调用是 `SVC 0xAB`，TinyUSB 守卫是 `BKPT #0` —— **看汇编码上下文**，
不要只数 `BKPT`。若确认是 DHCSR 守卫形态，记录为「已知无害」即可，不必除。

## 七、验收标准

- [ ] `build_log.htm` 末行 `0 Error(s), 0 Warning(s)`
- [ ] `Objects/` 下 `.axf` / `.hex` / `.bin` 均生成
- [ ] uvprojx 中不含 `syscalls.c`（`grep -c syscalls MDK-ARM/*.uvprojx` == 0）
- [ ] 半主机抑制垫片在 uvprojx 中且文件实际存在；
      `fromelf --text -s Objects/*.axf | grep -E "__use_no_semihosting|_sys_exit"` 有命中，
      `fromelf --text -c Objects/*.axf | grep -c "SVC.*0xab"` == 0
      （注意：`BKPT` 计数**可能非 0**，须按六·E 分辨是否为 DHCSR 守卫）
- [ ] 应用已实现第三方库要求的弱钩子（如 `tusb_time_millis_api`），无 `L6218E` 残留
- [ ] 段「加载地址 ≠ 运行地址」用两个平级 load region 表达（非嵌套）；
      `fromelf --text -s` 证实 `Load$$<ER>$$Base` 在 Flash、`Image$$<ER>$$Base` 在 RAM
- [ ] After-Build 用 `fromelf --bincombined`（多 load region 下 `--bin` 会产出目录）
- [ ] HAL 源按需引入：HAL 组内 `.c` 为个位数~十几个（非目录全量），与 CMake 侧 HAL 源列表一一对应；
      新增外设时两侧同步补齐
- [ ] `fromelf --info=totals` 的 ROM 大小与预期一致（与 CMake 侧同源集产物量级相当）
- [ ] **栈/堆与 GCC 侧逐项一致**（`grep -nE "Stack_Size|Heap_Size"` 两侧对比），
      且 `ZI-data` 增量 == 两处差值之和
- [ ] 语言级别够用：工程用了 `_Static_assert`（C11）或 C99 `T f(int a[static N])` 时，
      uvprojx 需 `uAC6=1` 且 C 级别给到 C99/GNU 变体（本项目 `uC99=1` + `uGnu=1` + `v6Lang=5`
      实测可编过这两者）；否则会报 `expected expression` 一类莫名其妙的语法错
- [ ] 第三方库**无 newlib 专有头依赖**（`grep -rn "_ansi\.h\|_BEGIN_STD_C" third_party/` 无命中）
- [ ] 帧缓冲落在 AXI SRAM（ZI ≈ `N × W × H` 字节，与 `.framebuffer` 段一致）
- [ ] 真机烧录/运行验证为可选后续（与 GCC 构建共用同一份源码逻辑）
