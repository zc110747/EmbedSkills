# 单文件日志模块范式、双工具链垫片与上板验证踩坑

## 一、单文件日志模块范式（GCC + ARMCLANG 共用同一份源码）

把「日志宏 + 串口 + 标准输出重定向」三件事收进**一个源文件**，让 CMake(GCC) 与 Keil(MDK-ARM) 编译同一份日志源码，不再维护两套割裂的垫片。多工具链工程首选这个形态。

### 1.1 文件布局与 API

- 一个头文件（开关宏 + 声明）+ 一个源文件（实现）。
- 串口外设 handle 定义在应用侧，头文件里 `extern` 引用。
- API：初始化 / 写入（data+len）/ `printf_log(fmt,...)` / `vprintf_log(fmt,ap)` / TX 中断服务函数 / 中断初始化。
- 日志宏是**两参形态**，无 level、无 tick 参数。

### 1.2 标准输出重定向：用「替换」而不是「补 `fputc`」

```c
/* 源文件尾部：GCC/newlib 下把 _write 接到自己的非阻塞环；
 * ARMCLANG(MDK) 下不编译此段 —— MDK 侧这一路根本不存在。 */
#if defined(__GNUC__) && !defined(__ARMCC_VERSION)
int _write(int file, char *ptr, int len)
{
    (void)file;
    uart_write((const uint8_t *)ptr, len);
    return len;
}
#endif
```

- 应用代码不再直接调 `printf()`，一律走日志宏 → 唯一 sink → 带 TX 环的非阻塞写入。**两个工具链都走同一条非阻塞路径**，无需在 Keil 侧另外补 `fputc` / `_sys_write`。
- 初始化里 `setvbuf(stdout, NULL, _IONBF, 0)`（关闭缓冲）：**只对 GCC/newlib 有效**；ARMCLANG 的 stdout 是另一套实现，此行在 MDK 下等于 no-op。
- 去掉 newlib 的 `syscalls` 垫片后，`--specs=nosys.specs` 仍在也没关系：`nosys` 提供的 `_write` 是 weak，会被自己定义的强符号覆盖，链接不冲突。

### 1.3 ARMCLANG 半主机抑制垫片不能删（易误判）

**这条最容易被搞错，方向与「删 syscalls」相反。**

- newlib 的 `syscalls` 垫片是 GCC 专用 → **必须从 Keil 工程排除**。
- ARMCLANG 的**半主机抑制**垫片（`__use_no_semihosting` / `__ARM_use_no_argv` + `FILE __stdout` + `_sys_exit` + `_ttywrch`）→ **必须保留**。

为什么 1.2 不能替代它：1.2 的 `_write()` 被 `#if defined(__GNUC__) && !defined(__ARMCC_VERSION)` 挡住，MDK 侧根本不编译这段，MDK 侧的日志走写入函数直出，与半主机无关。
但只要工程里出现**任何**直接调 `printf` / `fprintf` / `scanf` / `fopen` 的代码（包括第三方库和将来新加的调试语句），ARMCLANG 就会链入半主机实现 → 运行到 `_sys_open` / `_sys_write` 时执行 **`BKPT`** → 停机或 HardFault，表现是「串口无输出 / 程序莫名停住」。

⚠️ 这是**延迟暴露的坑**：删掉后编译链接**可能照过**（无裸 `printf` 时相关符号被 `--gc-sections` 丢弃），编译期拦不住，所以最易被误删。结论：单文件日志模块与半主机抑制垫片职责不同，**必须共存**。

验证（对 AXF 反汇编统计软断点数量）：

```bash
fromelf --text -c Objects/*.axf | grep -c " BKPT"    # 期望 0
```

### 1.4 迁移清单

1. 新增单文件日志模块（头 + 实现），可从同族工程整份复制。
2. 删除：newlib 的 `syscalls` 垫片、旧串口驱动（.c/.h）、旧日志头；**保留 ARMCLANG 半主机抑制垫片**。
3. 四参日志调用点全部改成两参（改调用点，不改宏）。
4. 中断向量文件增加 `USARTx_IRQHandler` → TX 中断服务函数。
5. 应用初始化：旧串口初始化 → 新日志初始化。
6. 构建脚本：源文件列表去掉 `syscalls` 与旧驱动，加入新日志模块。
7. Keil 工程文件：从对应源文件组删掉 `syscalls` 垫片，加入新日志模块；**半主机抑制垫片保持在组内**。
8. 删除旧日志头后确认无残留 `#include`。

**验证**：GCC 与 Keil 双构建均 0 error 0 warning；串口（115200 8N1）能抓到启动 banner。

## 二、上板验收踩坑

### 2.1 CRLF 行尾安全编辑（极易静默破坏）

仓库 `.c/.h` 多为 CRLF。naive 的 `text.split("\n")` 再 `"\r\n".join(...)` 会把行尾变成 `\r\r\n`，**翻倍**的 CR 会破坏 `#if` 行的 `\` 续行（报 "operator '&&' has no right operand"）。修法（二选一）：

- 二进制读写：逐行 `line.rstrip(b"\r")` 去掉尾部 CR，再按 `b"\r\n"` 回接；
- 或按**锚点局部二进制替换**（只在已知串前后插入），完全不碰行尾。

**严禁**用 `sed -i` 或整体 `"\n".join` 重写 CRLF 文件。

### 2.2 openocd `-c` 多词命令必须再套一层引号

某些 shell 下 `openocd -f openocd.cfg -c "init; reset run; exit"` 会被按空格拆成多个 token，报 `Unexpected command line argument: reset`。
正确写法：`openocd -f openocd.cfg -c '"init; reset run; exit"'`（外层单引号包住整个多词命令）。
单条命令无需内引号：`openocd -f openocd.cfg -c "program build/x.elf verify reset exit"`。

### 2.3 Windows PowerShell 5.1 `Start-Process` 环境块大小写重复键崩溃

会话可能注入 `http_proxy` / `HTTP_PROXY` 等大小写变体；PS 5.1 用大小写不敏感字典组装子进程环境块时会撞重复键抛「已添加项」，而 `Get-ChildItem Env:` 会把变体折叠成一项导致去重无效。修法（脚本顶部，干净终端下是 no-op）：

```powershell
$all = [System.Environment]::GetEnvironmentVariables('Process')   # 真实大小写变体名
foreach ($k in $all.Keys) { [System.Environment]::SetEnvironmentVariable($k, $null, 'Process') }
# 然后按需重建需要的变量（如 Path）
```

PS 7 无此问题；5.1 必须显式清理。

### 2.4 抓启动 banner：先开串口再复位

启动日志只在启动时打印一次。顺序必须是**先打开串口（115200 8N1）再复位目标**，否则 banner 已经刷过、抓不到。
pyserial 不可用时可用 .NET `System.IO.Ports.SerialPort` 读；若端口被拒，多半是上一次捕获的句柄未释放，或调试探针的虚拟串口在复位后重新枚举——**重试 + 短暂等待**即可。
