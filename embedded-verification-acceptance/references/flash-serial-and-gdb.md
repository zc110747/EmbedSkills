# 烧录、串口与 GDB 函数级调试

## 一、OpenOCD 烧录

```bash
openocd -f <board>.cfg \
  -c "init" -c "program build-release/<app>.elf verify reset exit"
```

成功标志：`** Programming Finished **` → `** Verify Started **` → `** Verified OK **` → `** Resetting Target **`。
顺带记录目标信息：调试器固件版本、Target voltage、SWD DPIDR（如 STM32H743 = `0x6ba02477`，STM32F429 = `0x2ba01477`），可用于确认"连上的是哪颗芯片"。

- ⚠️ **烧录必须用 `.elf`，不要用 `.bin`**：`.elf` 自带加载段与入口；`.bin` 会报
  `no flash bank found for address 0x00000000` 且 `wrote 0 bytes`。手动命令：
  `flash write_image erase build/<app>.elf` + `verify_image` + `reset run`。
- **改完代码后先烧录再抓串口**：只 `reset` 不复烧会看到旧固件行为，直接误判。
- Git Bash 里 `cd` 路径必须用正斜杠，反斜杠会吞掉目录分隔。

### 1.1 `mdw` 内存直读（正向验证）

- `halt` 后必须 `wait_halt`（或用批量脚本的固定等待）再读。
- **`mdw` 只能 4 字节对齐整字读**，非对齐地址报 `Failed to read memory`；读 `uint8/uint16` 混排的静态变量要按整字读再在 Python 里切字节。
- 一次性 `-c` 脚本的 stdout 会被 `shutdown` 前的缓冲吞掉，要落文件或改交互连接。
- 流程：`arm-none-eabi-nm <elf> | grep <symbol>` 取址 → `mdw` 直读目标内存，是"没报错 ≠ 有数据"的正向验证手段。

## 二、GDB 函数级调试：隔离验证与挂死定位

某个函数（如 Flash 擦写引擎）一跑就死、靠加日志难以定位时，用 **gdb 直调该函数**做隔离验证，并用**超时挂死检测**自动抓 PC。

### 2.1 起常驻 openocd 调试服务器（gdb :3333 / tcl :6666 / telnet :4444）

```bash
openocd -s <openocd scripts dir> -f openocd.cfg > ocd.log 2>&1 &
# openocd.cfg: interface/<debugger>.cfg + transport select swd + target/<chip>.cfg
```

后续 gdb / telnet 烧写都连这个服务器，**不要重复起 openocd**（调试器被独占，第二个实例会失败）。

### 2.2 gdb 直调函数（先 relocate RAM 引擎再 call）

很多函数依赖"从 RAM 执行的引擎"，必须先让 relocate 跑完：用硬件断点命中 relocate 函数，`finish` 执行完它，再 `call` 目标函数。

```gdb
target extended-remote :3333
monitor reset halt
file build/<boot>.elf                 # 载入符号表
break <RelocateFn>                    # hw-bp 命中 relocate
continue
finish                                # 执行完 relocate（引擎已搬到 RAM）
call <erase_fn>(1,2)                  # 返回 0 = OK
call <program_fn>(0x08xxxxxx, 0x24xxxxxx, 32)
x/8xw 0x08xxxxxx                      # 回读 8 字，应等于写入 pattern
```

若 `call` 后 gdb 长时间不返回 → 真机挂死（见 2.3）。

- ⚠️ **GDB 可靠性边界**：`-O2` / Release 下读局部变量不可靠；Cortex-M **勿用 `call` 触发复杂函数**（易 HardFault，尤其涉及 OS 调度 / 中断 / 浮点）。隔离验证优先 hw-bp + `finish` + `call` 简单函数。
- ⚠️ **断点打在「含 RTOS 互斥量获取」的函数会死锁**：内部取信号量在调度器未起或已有任务持锁时会永久阻塞 gdb。改法：断点打在 `vTaskStartScheduler()` **之前**，或确认此刻无持锁窗口；否则用"hw-bp 命中入口 → `finish` → 看返回值"代替交互式 `call`。

### 2.3 挂死自动检测

```python
p = subprocess.Popen([GDB, "-q", "-batch", "-ex", "target extended-remote :3333", ...])
try:
    p.wait(timeout=45)               # 超时则视为挂死
except subprocess.TimeoutExpired:
    p.kill()
    # 再起一个 gdb 连服务器，monitor halt，读 pc / lr / sp / backtrace
```

- **铁律**：Cortex-M7 的 DTCM(`0x20000000`) **不可执行代码**（I-Code 总线取不到指令）→ 从 DTCM 跑函数立即 BusFault → `Default_Handler` 死循环。凡"从 RAM 执行"的引擎**绝不放 DTCM**，必须放 AXI SRAM(`0x24000000`) 一类可执行 RAM。
- 卡在编程函数还要查：手搓的寄存器序列是否与参考手册一致。

### 2.4 用 gdb 读关键区做回读校验（不依赖串口）

```gdb
x/1xw <版本槽地址>      # 应等于刚烧进去的版本号
x/2xw <App 向量地址>    # SP / reset
x/4xw <配置区地址>      # magic + crc32
```

gdb 会剥前导零，比对时按 32 位值判断。

### 2.5 复用 running openocd 烧写（telnet 4444）

```python
s = socket.create_connection(('127.0.0.1', 4444))
send('reset halt')
send('flash write_image erase build/<boot>.bin 0x08000000')
send('verify_image build/<boot>.bin 0x08000000')   # 期望 verified N bytes
send('reset run')
```

避免再起 openocd 与调试器冲突。

### 2.6 运行时计数直读（验缓存命中率 / 算法行为，无需串口命令接口）

固件没有 UART 命令接口、却要确认某模块的 hit/miss/evict 计数是否真实生效时，**烧录 Debug 构建（带符号）+ gdb 直读静态变量**是最硬的证据，比串口打印更准（不受日志时序 / 缓冲干扰）。

```bash
openocd -f openocd.cfg -c "program build-debug/<app>.elf verify reset exit"
openocd -f openocd.cfg > ocd.log 2>&1 &
arm-none-eabi-gdb -batch -x read_counters.gdb build-debug/<app>.elf
```

```gdb
set pagination off
target remote :3333
monitor reset run          # 重新启动，跑自动业务
shell sleep 20             # 让缓存 / 算法充分运行
monitor halt               # 冻结
x/1uw &'<module>.c'::s_hits      # 直读符号真实地址
x/1uw &'<module>.c'::s_misses
x/1uw &'<module>.c'::s_evicts
detach
quit
```

- 必须用 `x/1uw &'file.c'::symbol` **直读符号真实地址**，不要 `call func(&$var)`：gdb 便利变量不能取地址，会报 `Attempt to take address of value not located in memory`。
- gdb 偶发 `This normally should not happen, please file a bug report` 多为 `printf` 路径噪声，不影响 `x/1uw` 结果。
- 验证完把板子刷回 Release 构建（生产态），并删掉临时 `.gdb` 脚本。

### 2.7 环境局限

- **QSPI 直写常常不可行**：openocd 的 `stmqspi` 在这类环境常拉不起 H7 的 QSPI（probe 后 timeout / No QSPI）。升级包改走**设计的可移动介质路径**（QSPI FatFs + TinyUSB MSC，由用户机器拷包）。

## 三、串口捕获与占用排查

```python
import serial
s = serial.Serial('<COM端口>', 115200, timeout=0.3)
```

- 报 `PermissionError` → 端口被**残留 python / 捕获进程**占用：先 `tasklist` 找占用者并结束，再抓。抓日志要在 `reset run` **之后**开始。
- 调试器被残留进程占用：烧录报 `Error: init mode failed` / `<debugger> not found` → `tasklist | findstr openocd` 找残留 PID，`taskkill /F /PID <pid>` 后再起新实例。同一时刻只能有一个 openocd 持有调试器。
- `libusb_open() failed with LIBUSB_ERROR_ACCESS`：反复用 openocd / gdb 后 USB 被残留进程占用 → 先杀 openocd 进程再烧。
- **COM 口 `code-31 / PermissionError(13)`**：CH340 等 USB 串口会周期性进入"设备未发挥作用"状态，需重新插拔才能恢复；串口挂掉时改用 **SWD 读内存取证**代替串口抓日志。
- 端口号依本机分配；Git Bash 下近似 `/dev/ttyS<N-1>`，原生 python 用 `COM<N>`。

### 3.1 调试器虚拟串口「拒绝访问」重试坑（高概率）

用 OpenOCD 经 libusb 触碰过调试器后，**首次打开其虚拟串口常报「拒绝访问 / PermissionError」** ——
即使 `tasklist` 查无占用者、没有残留 python 进程（与"端口被残留进程占用"是**两种不同根因**）。
根因是该 VCP 在 OpenOCD 释放后仍被 Windows 短暂持锁。

**解法**：串口捕获脚本对 `serial.Serial(...)` 做 **5~7 次重试（指数退避 0.2~1.5s）**，重试几次后必然成功；仍失败则重插调试器或重启 OpenOCD 再试。
**切勿**误判为"端口被占用去 kill 进程"—— 那种做法无效。
