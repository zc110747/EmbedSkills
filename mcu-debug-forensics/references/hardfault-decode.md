# HardFault 现场解码与"是否在跑"的判定

## 1. 现场寄存器采集

```bash
openocd -f <ocd.cfg> -c "init" -c "halt" \
  -c "reg pc" -c "reg lr" -c "reg sp" \
  -c "mdw 0xE000EDF0 1"   # DHCSR : bit1 C_HALT / bit17 S_HALT / bit19 S_LOCKUP
  -c "mdw 0xE000ED04 1"   # ICSR  : VECTACTIVE(bits 8:0) = 当前异常号（3 = HardFault）
  -c "mdw 0xE000ED28 1"   # CFSR  : BFSR(bits15:8) bit7 PRECISERR + bit1 BFARVALID
  -c "mdw 0xE000ED2C 1"   # HFSR  : bit30 FORCED（说明被升级成 HardFault）
  -c "mdw 0xE000ED38 1"   # BFAR  : 出错访问地址
  -c "mdw <sp> 8"         # 异常压栈帧
  -c "shutdown"
```

## 2. 异常压栈帧

handler 未再压栈时帧就在 MSP：

```
+0x00 R0   +0x04 R1   +0x08 R2   +0x0C R3
+0x10 R12  +0x14 LR   +0x18 PC   +0x1C xPSR
```

`+0x18` 的 `PC` 才是**出错指令**，`xPSR` 的 bit24(T) 应为 1。

## 3. 反汇编核对（不可省）

**不要用符号表里"最近符号"推断出错函数**：一堆 `*_IRQHandler` 是 weak 别名，
全部指向 `Default_Handler` 同一地址，`nm | awk '$1<=PC'` 会返回毫不相关的符号
（例如某个从未用到的外设中断处理函数）。看到 `PC` 落在 `Default_Handler` 上，
就去解压栈帧反推真正出错点。

```bash
arm-none-eabi-objdump -d --start-address=0x08001d38 --stop-address=0x08001d60 <elf>
```

有效的收尾方式：把出错指令的操作数偏移与 `BFAR` 对上。例如出错指令是
`ldr r3, [r0, #8]`（读某个外设寄存器的 `IDR`），而 `BFAR − R0 = 8` **正好等于该结构体
偏移** → 一句话证明"R0 是被当成外设端口基址用的野指针"，无需猜测。

## 4. 常见现象 → 含义对照

| 现象 | 含义 |
|---|---|
| `uwTick` 不涨 + `S_HALT=1` | 被调试器停住（不是固件 bug），`resume` 即可 |
| `uwTick` 不涨 + `S_HALT=0` + ICSR VECTACTIVE ≠ 0 | 卡在某个异常（多为 HardFault） |
| CFSR 全 0 + VECTACTIVE=0，但 `uwTick` 不涨 | 卡在普通 `while(1)` / 关中断临界区 |
| 空 Flash 时 `mdw 0x08000000` 全 `ffffffff`，`pc=0xfffffffe` | 目标侧 Cortex-M lockup，**非探针缺陷** |
| 双主机同时挂同一目标，读出确定性坏值（如 `DPIDR=0xff4c001b`） | 两个调试会话抢同一 DP，先断开另一个 |

## 5. "是否在跑"必须先判定，不要猜

`halt` / `resume` 不可靠时，判活要用**双采样**：

```bash
openocd -f <ocd.cfg> -c "init" -c "halt" -c "mdw <uwTick> 1" \
  -c "resume" -c "sleep 500" -c "halt" -c "mdw <uwTick> 1" -c "shutdown"
```

Δ=0 → 卡死，配合 §1 / §4 判断是否 HardFault。

**验收脚本要把这一步做成前置判定**：否则"uptime 不推进 / LED 不翻转 / 传输计数不增"
会一起 FAIL，多个红叉把真正的根因（一次 HardFault）盖住。正确做法是判死不通过时
**直接打印故障现场**，并**跳过**所有运行时段判据。

## 6. 复位标志寄存器（区分"被复位"与"内存被写坏"）

常见实现（如 STM32 的 `RCC_CSR`）：bit26 PINRSTF / bit27 PORRSTF / bit28 SFTRSTF /
bit29 IWDGRSTF / bit30 WWDGRSTF / bit31 LPWRRSTF，bit24 为清除位。

**"内存被写坏"与"掉电 / 看门狗复位后跑了新的一轮"现象极像，必须分开**：
读复位标志看是否新增位，并用 `uwTick` 回退兜底（计数器倒回去 = 目标重启过）。
