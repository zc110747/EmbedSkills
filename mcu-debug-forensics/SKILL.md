---
name: mcu-debug-forensics
description: MCU 调试取证：SWD/OpenOCD 读内存、HardFault 现场解码、中断不进、自研 CMSIS-DAP 探针调优。用于串口或示波器不可用时怎么验证。
agent_created: true
---

# MCU 调试取证

## 何时用

- 串口/日志不可用（口打不开、驱动故障、日志被限流），需直接用 SWD 读目标 RAM 验证行为。
- 板子"像死了"：串口无输出、屏幕不刷新、按键无响应——先定性，再查固件。
- 中断不进 / EXTI 不触发 / 中断风暴 / I2C 总线锁死 / HardFault / 疑似 RAM 被写坏。
- 自研 CMSIS-DAP 探针移植与位带调优、下载慢、OpenOCD 连不上。

## 核心知识点

| 主题 | 要点 |
|---|---|
| 读内存 | `mdw` 只支持 4 字节对齐整字读；`uint8_t`/`uint16_t` 混排的静态区先整字读回再按字节切。 |
| 符号地址 | 地址随构建变化，用 `arm-none-eabi-nm` 现取，禁止硬编码；镜像路径给绝对路径 + 正斜杠（MSYS 风格与相对路径都会失败）。 |
| 读的是谁的内存 | 任何"读内存→下结论"前先 `verify_image` 比对板上镜像：同源码的不同构建 `.bss` 布局不同，符号会错位。 |
| 停稳 | `halt` 后必须 `wait_halt` 再 `mdw`；判活用计数器双采样看增量，不看单次值。 |
| HardFault | `ICSR.VECTACTIVE` 定异常号 → `CFSR` 的 PRECISERR/BFARVALID → `HFSR.FORCED` → `BFAR` 给出错地址；异常压栈帧 `+0x18` 才是出错 PC。 |
| 反汇编核对 | 一堆 `*_IRQHandler` 是弱别名、全指向 `Default_Handler`，按"最近符号"推断会得到毫不相关的名字。 |
| 中断诊断 | 向 `EXTI->SWIER` 写位可免手指验证 EXTI→NVIC→回调全链路（ISR 自屏蔽该线时先开 `IMR`）；给可疑中断加 1 秒窗口速率计数，把"风暴"变成 `N/s` 再判断。 |
| 探针位带时序 | 延时用 DWT `CYCCNT` 自旋，不用假设每轮固定周期的内联汇编循环（多发射/缓存会让实际时钟偏快）；`CPU_CLOCK` 必须与实际 SYSCLK 一致。 |
| HID 协议上限 | v1 over HID 的 IN 端点靠主机约 1 kHz 轮询，每条命令下限 ≈1 ms，与时钟无关。 |
| 无线探针仲裁 | USB 与 Wi-Fi 互斥；判定主机存在用 `tud_mounted()`，`tud_connected()` 只代表 VBUS。 |
| 量化验证 | 用 `volatile`、非 `static` 的字节计数器替代示波器，必须采两次看增量。 |
| 工作区算法（★ 高价值） | OpenOCD 的 flash / CRC32 校验算法会被写进 `-work-area-phys` 指的那块 RAM，并**驱动 CPU 的 PC 跳进去执行**。在"刚做过 flash/verify/checksum"的窗口里读到 `PC` 落在工作区、`CFSR≠0`，那是**调试器自己的痕迹**，不是固件跑飞。指纹：CRC32 的 `0x04C11DB7` 会出现在工作区里。 |
| 判"固件是否崩" | 唯一可信姿势：**`写 CFSR=0 → resume 跑 N 秒 → halt 读 CFSR`**。绝不能在刚做完 flash/verify/checksum 的会话里读 `CFSR` 下结论。反例：`verify_image` 后 `CFSR` 实测为 0、`PC` 在主循环，而"自由运行 90 s、uwTick 推进 91057 ms、CFSR=0"才证明固件健康。 |
| **flash/verify 会话必须以 `reset run` 收尾**（★ 高价值） | `verify_image` 跑完就 `shutdown` ⇒ CPU 被**留在工作区算法里**（实测 `PC=0x2000802e`、Thread 模式、`CFSR=HFSR=0`），并告警 `target was in unknown state when halt was requested`。此后任何会话的 `resume` **都不会真正让固件跑起来**（没有可信上下文可恢复）⇒ `uwTick` 冻死在同一值。**后果极具欺骗性**：后续所有"判活/时序"类脚本集体报 FAIL，看起来像固件跑飞或一堆功能同时坏了。**修法**：flash/verify 的那个 openocd 序列在 `shutdown` 前补 `-c "reset run"`（mdw 取数仍在 halt 态完成，检测力不受影响）；判读前不确定就先 `init; reset run; shutdown` 还 PC 给固件。 |
| 工作区选址 | `-work-area-phys` 必须显式避开固件 RAM：取"静态区上界 `_end` 与栈顶 `_estack` 之间"。F1 上默认 `0x20000000` 正好压 `.data`；且 `-work-area-backup 0` 意味着**用完不清理**，算法代码会持久残留（事后 dump 仍看得见）。 |
| 节奏档位 | `Unable to match requested speed 1000 kHz, using 950 kHz` 说明实际速率已被降档；档位过高会让目标侧 flash 算法超时（`timeout waiting for algorithm`）**并把 Flash 擦空**。 |
| 单向增量编码器的「绕回伪装」（★ 高价值） | 用**无符号**差值（`(uint16_t)(now − prev)`，模 65536）表达"量程内单向计数"时，**反向转动**会绕成 `65536 − k` —— 一个"正向转了半圈"的超大正值。它安静地穿过窗口累加 → 平均 → 标定换算，**中途任何一处都不报错**，直到末端才表现为**被钳位到显示上限的合法最大值**（现场观感："某一瞬间闪一下满量程"，且只闪一下就会自恢复，因为下个窗口重算）。判据取"两个解释里唯一可信的那个"：`d > SANE` 时若 `65536 − d ≤ SANE` 判**绕回**并上报负值，两者都超 `SANE` 判 `0`（丢弃）；`SANE` 取**满速窗口增量的 8 倍左右** —— 既留足冲击/堵转余量，又远小于半量程 32768 ⇒"绕回"与"真的这么快"永不混淆。 |
| 显示/输出钳位要取「机器物理上限」，别取「栏位容量」 | 把测量值钳到"能塞进显示栏位的最大值"（3 位 → 99.9）会把**测量假象**渲染成一个看着完全合法的最大值，等于替 bug 做掩饰；钳到"这台机器物理上不可能超过的上限"（如最大设定速度）假象立刻显形。附带纪律：验收脚本复刻同一钳位时必须**从同一个真值源派生** —— 脚本里另抄一个 `999` 就是**第二真值源**（固件改了钳位、脚本照旧按旧上限期望，两边"一致"却谁也没验到钳位这一环）。 |

## 判据与反模式

- 读到的内容"不像这个程序写的"→ 先怀疑符号与板上固件不匹配，别先怀疑固件逻辑。
- 同一地址两次读出不同 → 先怀疑读取时刻/对象（未真正停稳），再谈"被改写"。
- 只看一次计数器绝对值 → 会把"停在半帧"误判成"传输被截断"。
- 监视点撒点式覆盖整段 → 命中到会被反复写的状态字段即假命中，长跑窗口作废；只压"仅在初始化时写一次"的字段。
- 长跑每轮重开调试器 → 丢监视点与命中现场；用常驻单会话 + 唯一 echo 标记做输出同步。
- 跑够历史崩溃时间的数倍仍 0 命中 → 判为间歇性并登记已排除项，不能下"没有这个 bug"。
- "内存被写坏"与"被复位后跑了新的一轮"现象极像，必须用复位标志 + 计数器回退分开。
- 验收脚本把"判活"当普通判据 → 一次 HardFault 会让多条判据同时红、盖住根因；判死时直接打印故障现场并跳过运行时段判据。
- 下"板子像死了"的结论前，先查是否有调试会话正持有探针（停在断点 = CPU 被 halt）。
- **探针"集体假故障"指纹**：一串互不相关的验收脚本**同时**大面积 FAIL（尤其"活性/节拍不推进"这类），先查探针与目标状态，别去读固件代码。两级先查：① 是否有进程占着 ST-Link；② `Get-PnpDevice -PresentOnly | ? InstanceId -match 'VID_0483'` 看 `Status` 是不是 `Error`。实测踩过两次：探针掉链子时 39/43 条判据齐红、`s_ctrl_ticks` 冻结，看着像 TIM4 中断没跑，其实固件一直健康。
- **ST-Link `Status=Error / CM_PROB_HELD_FOR_EJECT`**（Code 47，"已准备安全移除但未拔出"）：症状是 `openocd` 报 `libusb_open() failed with LIBUSB_ERROR_NOT_SUPPORTED`（**不是** `LIBUSB_ERROR_ACCESS` —— 后者才是被别的进程占用）。**不用拔插**：`Enable-PnpDevice -InstanceId <id> -Confirm:$false` 即可复位到 `OK`（`Disable-PnpDevice` 反而可能报"常规故障"，但 enable 仍有效）。密集会话（几十次 openocd 起停）后高发。
- 读到 `PC` 落在 RAM 里 → **先量它是不是自己的工作区地址区间**，别先判固件跑飞；固件代码段在 Flash，正常执行路径不会落进 `-work-area-phys`。
- `CFSR` 非零 ≠ 固件 bug → 先问"这个会话里我做过 flash/verify/checksum 吗"。这类操作会让 CPU 去执行工作区算法，被 1ms `SysTick` 或 SWD 毛刺打断就报 `IMPRECISERR`。
- 把工作区换个地址就以为修好了 → 换地址只是**换了个受害者**。必须用 `nm` 现取 `_end` / `_estack`，确认新地址既不压静态区也不压栈，并写进配置注释。
- 拿记忆/旧脚本里的符号地址读新构建 → 改过宏或结构体布局就会移地址，读出一串错位值还会伪装成"数据被写坏"。**符号地址永远用 `nm` 从当前 ELF 现取。**

## 详细资料

- `references/swd-memory-read.md` — mdw 读结构与 Python 切字节、verify_image 锁镜像、reset halt 陷阱、.data 三处对照、指纹搜索、写监视点选址与长跑常驻单会话。
- `references/hardfault-decode.md` — 故障寄存器与压栈帧逐位说明、反汇编核对、判活双采样、复位标志、现象-含义对照。
- `references/dap-probe-tuning.md` — 位带延时与时钟配置、IRAM/驱动强度、JTAG `Invalid ACK (4)` 根因、HID 上限、USB/Wi-Fi 仲裁、主机侧逐级验收与假故障表、探针占用排查。
- `references/interrupt-tracing.md` — EXTI 软件注入配方、中断风暴定位与防护、I2C 锁死恢复判据、无相机量化验证判据。
