---
name: mcu-debug-forensics
description: MCU 调试取证：SWD/OpenOCD 读内存与 HardFault 现场解码，自研 CMSIS-DAP 探针调优与主机侧验收。适用于"读内存验证变量""HardFault 定位""中断不进""探针下载慢"等请求。
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

## 详细资料

- `references/swd-memory-read.md` — mdw 读结构与 Python 切字节、verify_image 锁镜像、reset halt 陷阱、.data 三处对照、指纹搜索、写监视点选址与长跑常驻单会话。
- `references/hardfault-decode.md` — 故障寄存器与压栈帧逐位说明、反汇编核对、判活双采样、复位标志、现象-含义对照。
- `references/dap-probe-tuning.md` — 位带延时与时钟配置、IRAM/驱动强度、JTAG `Invalid ACK (4)` 根因、HID 上限、USB/Wi-Fi 仲裁、主机侧逐级验收与假故障表、探针占用排查。
- `references/interrupt-tracing.md` — EXTI 软件注入配方、中断风暴定位与防护、I2C 锁死恢复判据、无相机量化验证判据。
