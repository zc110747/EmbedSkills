# 日志系统设计：架构、宏、栈缓冲、构建开关与迁移

## 1. 三层架构（绝不重入串口发送锁）

```
PRINT_LOG(fmt, ...)
   └─> printf_log()                        // 应用唯一日志 sink
         └─> vsnprintf(buf, N, fmt, ap)    // 栈缓冲，不分配堆
               └─> uart_write(buf, len)    // 显式长度写入 TX 环
```

为什么不能直接用 `printf`：

- newlib 的 `printf` 最终走 `_write`，其内部对串口（HAL UART 发送等）持锁；并发或中断上下文里互相踩会产生「日志时有时无 / 串口卡死」。
- 自己 `vsnprintf` 进栈缓冲再显式长度写入 TX 环，路径上没有任何共享的可重入锁。
- 栈缓冲不分配堆，所以 boot 阶段（调度器未起）和堆已损坏时仍能打日志。

## 2. 日志头：开关宏 + 声明

```c
#ifndef PRINT_LOG_ENABLE
#define PRINT_LOG_ENABLE 1
#endif

void printf_log(const char *fmt, ...);
void vprintf_log(const char *fmt, va_list ap);

#if PRINT_LOG_ENABLE
  #define PRINT_LOG(fmt, ...)   printf_log(fmt, ##__VA_ARGS__)
#else
  #define PRINT_LOG(fmt, ...)   ((void)0)
#endif
```

约束（写进代码评审清单）：

- 日志宏**不能在 ISR 里调**：内部可能取 UART 互斥量（如 `uxSemaphoreGetMutexHolder` 在 ISR 里非法）。中断上下文用串口直写函数。
- 二进制 / 无 NUL 结尾的内容 dump（如文件系统目录遍历）**不要走日志宏**：`%s` 遇到 `0x00` 会崩。保持串口直写，并自己用 `#if PRINT_LOG_ENABLE` 包住。
- 日志宏保持「格式串 + 可变参」两参形态。若历史代码是 `LOG(LEVEL, tick, fmt, ...)` 四参形态，迁移时**改调用点**，不要改宏去兼容。

## 3. 日志实现：栈缓冲 + 早返回

```c
#define LOG_BUF_SIZE 192   /* 留足余量；vsnprintf 超长会截断 */

void vprintf_log(const char *fmt, va_list ap)
{
#if PRINT_LOG_ENABLE == 0
  (void)fmt; (void)ap; return;
#else
  char buf[LOG_BUF_SIZE];
  int n = vsnprintf(buf, sizeof(buf), fmt, ap);
  if (n < 0) return;
  if (n > (int)sizeof(buf) - 1) n = (int)sizeof(buf) - 1;
  uart_write((const uint8_t *)buf, n);
#endif
}

void printf_log(const char *fmt, ...)
{
#if PRINT_LOG_ENABLE == 0
  (void)fmt; return;
#else
  va_list ap; va_start(ap, fmt);
  vprintf_log(fmt, ap);
  va_end(ap);
#endif
}
```

要点：

- 关闭时函数体仍保留早返回，避免「宏关了但函数被别处直接调用」还能输出。
- 关闭分支显式 `(void)` 掉参数，才能在 `-Wall -Wextra` 下零警告。
- 栈缓冲尺寸按最长的实际日志行取，留余量；不确定时保守取大一点（192~256 量级）。

## 4. 构建系统一键开关

```cmake
option(ENABLE_PRINT_LOG "Compile in PRINT_LOG() application logging" ON)
if(ENABLE_PRINT_LOG)
  add_compile_definitions(PRINT_LOG_ENABLE=1)
  message(STATUS "PRINT_LOG: enabled (PRINT_LOG_ENABLE=1)")
else()
  add_compile_definitions(PRINT_LOG_ENABLE=0)
  message(STATUS "PRINT_LOG: compiled out (PRINT_LOG_ENABLE=0)")
endif()
```

关日志构建：`cmake -S . -B build_nolog -DENABLE_PRINT_LOG=OFF && cmake --build build_nolog`。
用 `option` 而非硬编码的好处：同一个仓库能同时产出「全开调试固件」和「零日志发布固件」。

## 5. 替换与迁移清单

1. 全工程 `printf(` → `PRINT_LOG(`；保留 `snprintf` 这类纯字符串格式化。
2. ISR 内的 `printf` → 串口直写。
3. 旧日志头 / 旧串口驱动 / 旧标准库垫片收敛到统一日志模块（见 `toolchain-and-verification.md`），确认无残留 `#include` 旧头文件。
4. 构建脚本：源文件列表去掉被替换掉的垫片与旧驱动，加入新日志模块。
5. 四参宏调用点逐个改成两参。
6. 若发现裸 `printf` 仍出现在第三方库里，工具链垫片必须保留（见 `toolchain-and-verification.md` 的半主机一节）。

## 6. 验收

1. **双构建零警告**：开关 ON / OFF 两种配置在 `-Wall -Wextra` 下都要干净。
2. **省下来的空间**：对比两种构建的 FLASH/RAM 占用，报差值（绝对量随工程规模变化，实测常在数 KB 量级）。
3. **开关真生效**：关日志后 TX 环写指针必须恒为 0、busy 标志恒为 0——即「一个字节都没进环」，而不只是「串口上没看到输出」。串口不可用时用调试探针读内存判定。
4. **上板**：烧录后串口（115200 8N1）能抓到完整启动 banner。
