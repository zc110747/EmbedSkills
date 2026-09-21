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

## 四、重写 uvprojx（关键字段）

- `<TargetName>` / `<Device>STM32<型号>xx</Device>` / `<PackID>Keil.STM32<系列>xx_DFP.<版本></PackID>`
- `<pCCUsed>6140000::V6.14::ARMCLANG</pCCUsed>`、`<uAC6>1</uAC6>`
- **Thumb 必开**：`<Cads><uThumb>1</uThumb>` 且 `<Aads><thumb>1</thumb>`。
  旧工程若误设 `uThumb=0` 会生成非法 ARM 态代码（Cortex-M 只认 Thumb）。
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

## 五、UV4 命令行构建与日志解析

```bat
"<Keil>\UV4\UV4.exe" -b -j0 -t <target> -x "<工程>\MDK-ARM\<target>.uvprojx" -o "<工程>\MDK-ARM\build_log.htm"
```

- `-b` 批构建；`-j0` 不限并发；`-t` 指定 target；`-o` 写 HTML 日志。
- **stdout 不一定回显**，判断成败靠 `build_log.htm` 末行：
  `"Objects\<target>.axf" - 0 Error(s), 0 Warning(s).`
- 退出码 `0` = 成功，`2` = 有错误。
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
| 设备解析失败 | DFP 版本/路径不对 | 装对 DFP 版本，确认 `PackID` |
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

## 七、验收标准

- [ ] `build_log.htm` 末行 `0 Error(s), 0 Warning(s)`
- [ ] `Objects/` 下 `.axf` / `.hex` / `.bin` 均生成
- [ ] uvprojx 中不含 `syscalls.c`（`grep -c syscalls MDK-ARM/*.uvprojx` == 0）
- [ ] 半主机抑制垫片在 uvprojx 中且文件实际存在；
      `fromelf --text -c Objects/*.axf | grep -c " BKPT"` == 0
- [ ] HAL 源按需引入：HAL 组内 `.c` 为个位数~十几个（非目录全量），与 CMake 侧 HAL 源列表一一对应；
      新增外设时两侧同步补齐
- [ ] `fromelf --info=totals` 的 ROM 大小与预期一致（与 CMake 侧同源集产物量级相当）
- [ ] 帧缓冲落在 AXI SRAM（ZI ≈ `N × W × H` 字节，与 `.framebuffer` 段一致）
- [ ] 真机烧录/运行验证为可选后续（与 GCC 构建共用同一份源码逻辑）
