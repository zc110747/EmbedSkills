# SWD 读内存取证

## 1. 通用模板

`mdw` 只支持 4 字节对齐的整字读。读 `uint8_t` / `uint16_t` 混排的静态区，必须先按
4 字节对齐整字读回，再按字节位置切出来。

```bash
# 取符号地址（不同构建地址不同，不要硬编码）
arm-none-eabi-nm <elf> | grep <symbol>

# 烧录 + 运行 + halt + 按 4 字节对齐整字读
openocd -s <scripts> -f interface/<probe>.cfg -f target/<chip>.cfg \
  -c init -c "reset halt" \
  -c "flash write_image erase <elf>" -c "verify_image <elf>" \
  -c "reset run" -c "sleep <ms>" -c "halt" \
  -c "mdw 0x20001000" -c "mdw 0x20001004" ...
```

### halt 时序与读数落盘

- `halt` 后务必跟 `wait_halt` 再 `mdw`：刚发 `halt` 时目标可能还在跑，立刻读 SRAM 会报
  `Failed to read memory`；`wait_halt` 等真正停稳后再读即正常。
- 用 `-c "init; ...; mdw ...; shutdown"` 一次性脚本时，**成功的 `mdw` 行常在 `shutdown`
  前被缓冲丢弃**（只透出错误行与 PC 行）。稳法：把输出重定向落盘再 grep，或先把所有
  `mdw` 做完、最后单独发 `shutdown`。
- 本类环境里 `halt` / `resume` 并不可靠：`init` 后直接 `resume` 可能报
  `Error: [<cpu>] not halted / context restore failed, aborting resume`；未真正停稳时
  `mdw` 还可能读到"看起来合理"的活跃内存，直接导出错误结论。

### Python 侧取回与切字节

```python
import re, subprocess

def read_struct(elf, addr, size):
    words = range(addr & ~3, (addr + size + 3) & ~3, 4)
    cmds = ["init", "reset halt", "flash write_image erase %s" % elf,
            "verify_image %s" % elf, "reset run", "sleep <ms>", "halt", "wait_halt"]
    for w in words:
        cmds.append("mdw 0x%08X" % w)
    cmds.append("shutdown")
    p = subprocess.run([OCD, "-s", SCR, "-f", "interface/<probe>.cfg",
                        "-f", "target/<chip>.cfg"] + sum((["-c", c] for c in cmds), []),
                       capture_output=True, text=True, timeout=300)
    vals = {}
    for line in (p.stdout + p.stderr).splitlines():
        m = re.match(r"\s*0x([0-9a-fA-F]{8}):\s+([0-9a-fA-F]{8})\s*$", line)
        if m:
            vals[int(m.group(1), 16)] = int(m.group(2), 16)
    raw = bytearray()
    for a in range(addr, addr + size):
        raw.append((vals[a & ~3] >> (8 * (a & 3))) & 0xFF)
    return bytes(raw)
```

## 2. 读内存前先证明"读的是谁的内存"

**症状**：dump 显示缓冲区只有开头一页有内容、后面全空、文字在行中间断掉 →
结论"渲染只做了第一行"。**这个结论是假的。**

**根因**：板上跑的是 Debug 构建，脚本的符号取自 Release ELF。两个构建的 `.bss` 布局不同
（实测偏移 8 字节），结构体与其内嵌缓冲区的地址整体错位，于是从缓冲区中间开始读，
结构体头几字节与前若干字节拼在一起，产生"文字断掉 + 后面全空"这种**看起来极其合理的假象**。

**规矩**：任何"读内存 → 下结论"之前，先比对板上镜像：

```bash
openocd -f <ocd.cfg> -c "init" -c "halt" \
  -c "verify_image <绝对路径>/build/<Debug|Release>/<image>.bin 0x08000000" \
  -c "resume" -c "shutdown" 2>&1 | grep -E "^diff|checksum"
```

- 输出 `Error: checksum mismatch - attempting binary compare` 与
  `diff 0 address 0x08000004. Was 0x29 instead of 0x0d` 即铁证。
- **差异从 `0x08000004`（复位向量）就开始** = 板上固件与你以为的不是同一份。
- `verify_image` / `dump_image` 的路径必须给 **Windows 绝对路径 + 正斜杠**（`D:/...`）：
  MSYS 风格 `/d/...` 会报 `couldn't open`，相对路径会被写到找不到的位置
  （Tcl 解释器有自己的 CWD）。

**判据不要靠看图猜**：把期望值在 Python 里复现（从源码解析字库表 + 照抄格式化串 +
同款位语义），逐字节比对，输出差异的**页/列/坐标**。ASCII 点阵图人眼极易误判。

## 3. `reset halt` 的陷阱

`reset halt` 停在**复位向量**，`.data` 尚未搬运，此时读 RAM 拿到的是**上次运行的残留**：

```bash
openocd -f <ocd.cfg> -c "init" -c "reset halt" -c "mdw <VMA> 12"                  # 残值/垃圾
openocd -f <ocd.cfg> -c "init" -c "reset halt" -c "resume" -c "sleep 3000" \
  -c "halt" -c "mdw <VMA> 12"                                                     # 搬运后的真值
```

差一步就会误判成"启动搬运把 RAM 写坏了"。**判定搬运问题必须带 `resume` 等待。**

## 4. `.data` 真值三处对照法

```bash
arm-none-eabi-objdump -h <elf> | grep -E "Idx|\.text|\.data|\.bss"   # VMA / LMA / size
arm-none-eabi-nm <elf> | grep -E "_sidata|_sdata|_edata|_sbss|_ebss"
arm-none-eabi-objdump -s -j .data <elf> | head                       # ELF 里的初值
# 板上：Flash @LMA 处内容  与  RAM @VMA 处内容
```

- 三处一致 → 搬运没问题，问题在运行期。
- **只有 RAM 与另两处不同** → 指向"运行期被改写"。
- Flash@LMA 与 ELF 初值就不同 → 段的 LMA 摆放 / 镜像生成有问题
  （先看 `objcopy -O binary` 出来的 `.bin` 长度是否覆盖到 `.data` 末尾）。
- RAM 内容在两次读之间变化时，**先怀疑读取时刻/对象不对**，再谈"被改写"。

## 5. 异常字节指纹搜索

把异常字节（`mdw` 输出按**小端**转字节流）当指纹，在镜像里做多位移、多窗口长度搜索：

```python
raw = b''.join(struct.pack('<I', w) for w in words)     # mdw 值 -> 字节流
for n in (32, 24, 16, 12, 8):
    for shift in range(4):
        if (i := data.find(raw[shift:shift+n])) >= 0:
            print(n, shift, hex(FLASH_BASE + i))
```

- **命中** → 某段 Flash 被拷到了 RAM（查 memcpy / 搬运循环 / 段摆放）。
- **全 0 命中** → 内容是**运行期生成的**，不要再往"拷贝错"方向查。
- 判据：多次崩溃的垃圾字节几乎逐字节相同（仅个别字节差异）⇒ **确定性写入**，
  不是随机噪声或失控执行；每次都不同则先怀疑供电 / EMI 跑飞。

## 6. 硬件写监视点

```bash
# boot 之后再设，否则会被 .data 拷贝本身触发
openocd -f <ocd.cfg> -c "init" -c "reset halt" -c "resume" -c "sleep 3000" -c "halt" \
  -c "wp <addr> 4 w" ... \
  -c "resume" -c "sleep 600000" -c "halt" \
  -c "reg pc" -c "reg lr" -c "reg sp" -c "mdw <VMA> 24" \
  -c "mdw 0xE000ED04 1" -c "mdw 0xE000ED28 1" -c "shutdown"
```

**铁律：只能压「只在启动时写一次」的字段。**

反例：把监视点均匀撒在整段以覆盖所有字节，结果 `resume` 后立刻"命中"，PC 落在按键扫描
函数里，压中的是**每次扫描都会写的去抖状态字段** → 假命中。更糟的是命中后 OpenOCD 去读
DWT 数据地址常失败并刷一片 `Fail reading CTRL/STAT register`，**整个长跑窗口作废**，
最后读到"`.data` 正确、CFSR=0"还会让人误判成"没崩"。

**正确做法**：先反汇编 / 看结构体，找出**只初始化一次**的字段（例如各通道的端口号与引脚号，
只有 `xxx_init()` 写），每个监视点精确压在一个该字段上，正好用满 Cortex-M3/M4 的
4 个 DWT 比较器。**撒点式"覆盖整段"是错的。**

其它要点：

- 长度只能 1/2/4 字节，无 mask；命中后目标自动停住，`reg pc/lr` 就是写入者现场。
- **必须同时读满整段**（如整个 `.data`）——只读开头几十字节**得不到跨度**，
  而"从哪个绝对地址开始、覆盖多少字节"往往就是定位写入者的关键线索。
- 跑够历史崩溃时间的数倍仍 0 命中 ⇒ **问题间歇性**：不要下"没有这个 bug"，
  写入未决项并注明已排除项。

## 7. 长跑必须用常驻单会话

每轮重开一次调试器会**丢监视点**，更慢、也更容易撞上 USB 占用。正确姿势是常驻一个
openocd 进程、用 stdin 喂命令，用 `echo <唯一标记>` 做输出同步（等到标记出现即表示该批
命令跑完）：

```python
proc = subprocess.Popen([OPENOCD, "-f", cfg], stdin=PIPE, stdout=PIPE,
                        stderr=STDOUT, text=True, bufsize=1)
# 起线程按行收 stdout；cmd() = 写命令 + 写 "echo MARK" + 等 MARK 出现，返回其间输出
```

每轮采样这 5 类判据，缺一类就会误判：

| 判据 | 读什么 | 说明 |
|---|---|---|
| 监视点命中 | halt 输出含 `due to watchpoint` | 命中即拿到写入者 PC |
| 故障 | `CFSR` != 0 | 总线 / 用法故障（配合 `HFSR`/`BFAR`） |
| 内存被改写 | 目标变量 vs **ELF 初值** | 期望值取自 `objcopy --only-section=.data`，别在脚本里复写数字 |
| 被复位 | 复位标志寄存器新增位 | 见 `hardfault-decode.md` §4 |
| 被复位（兜底） | `uwTick` 回退 | 计数器倒回去 = 目标重启过 |

> **静默坑**：`objdump -h` 的列序是 `Idx Name Size VMA LMA FileOff Algn`。按 `VMA/LMA/Size`
> 取会得到 `.data` 这种段一个荒谬的 VMA 值 —— 加一条"VMA 必须落在 RAM 区间"的自检即可当场拦住。
