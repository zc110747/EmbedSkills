# TX 路径：RTOS 双路径 + 懒互斥量，与裸机 TX 中断驱动变体

## 一、RTOS：双 TX 路径 + 懒互斥量（最易踩坑）

### 1.1 为什么互斥量不能在建串口时创建

串口初始化常在 SDRAM 初始化 / `vPortDefineHeapRegions()` **之前**被调用，此时 RTOS 堆尚未定义。
在 init 里创建互斥量，对象会落在未定义的堆上（表现为后续运行期异常，而不是启动即崩）。

正解：**调度器运行后、第一次写入时才惰性创建**，并用临界区包住创建，保证线程安全。

```c
static SemaphoreHandle_t g_tx_mutex = NULL;

static SemaphoreHandle_t tx_mutex_get(void)
{
  taskENTER_CRITICAL();
  if (g_tx_mutex == NULL)
    g_tx_mutex = xSemaphoreCreateMutex();
  taskEXIT_CRITICAL();
  return g_tx_mutex;
}

int uart_write(const uint8_t *data, int len)
{
  /* boot 阶段（调度器未起）或串口未就绪：阻塞轮询发送，绝不丢字节 */
  if ((g_uart_ready == 0) ||
      (xTaskGetSchedulerState() != taskSCHEDULER_RUNNING))
  {
    if (g_uart_ready == 0) return 0;
    HAL_UART_Transmit(&huartX, (uint8_t *)data, (uint16_t)len, HAL_MAX_DELAY);
    return len;
  }

  SemaphoreHandle_t mtx = tx_mutex_get();
  if (mtx != NULL && xSemaphoreTake(mtx, portMAX_DELAY) != pdTRUE)
    return 0;

  taskENTER_CRITICAL();                     /* 保护环计数器 + busy 标志 */
  for (int i = 0; i < len; i++) {
    uint16_t next = (g_tx_head + 1) & (UART_TX_BUF_SIZE - 1);
    if (next == g_tx_tail) break;           /* 满 -> 静默丢弃剩余字节 */
    g_tx_buf[g_tx_head] = data[i];
    g_tx_head = next;
    queued++;
  }
  if (g_tx_busy == 0 && g_tx_head != g_tx_tail) {
    g_tx_busy = 1;
    SET_BIT(huartX.Instance->CR1, USART_CR1_TXEIE);   /* 启动 TXE 中断搬运 */
  }
  taskEXIT_CRITICAL();

  if (mtx != NULL) xSemaphoreGive(mtx);
  return queued;
}
```

### 1.2 关键点

- **双路径判据**是「调度器是否 RUNNING」+「串口是否 ready」，不是「是否在中断里」。启动早期没有互斥量可用，必须退化到阻塞发送。
- 环计数器（head/tail）与 busy 标志的修改必须在临界区内，ISR 也会动它们。
- 返回 `queued` 而不是 `len`：环满时按实际入队字节数返回，便于上层判断是否发生丢弃。
- 环容量的下限要实测：**512 字节在 115200 下任意连续打印即爆**，实际取 **≥ 2048**。
- 批量打印（dump 大对象）必须限流：超过阈值只列目录项、整轮遍历设总字节预算，否则会静默丢掉其它任务的日志。
- 互斥量只保护「写环」这一小段；真正的发送在中断里完成，因此日志对任务是非阻塞的。

## 二、裸机（无 RTOS）变体：TXE 中断驱动环形缓冲

无 RTOS 时不能用互斥量保护 TX 环。改用 **TXE 中断驱动的环形缓冲**，临界区靠 **关闭串口 TX 中断**。

### 2.1 组件

- 日志头：编译期开关 + `printf_log()` / `vprintf_log()` + TX 中断服务函数（ISR 侧）+ 中断初始化函数（使能 NVIC）。
- 日志实现：
  - 栈缓冲格式化（同上，`LOG_BUF_SIZE` 取 256 量级）；
  - TX 环形缓冲 `UART_TX_BUF_SIZE` 取 1024 量级，读写指针与计数用 `volatile`；
  - 写入函数：写前 `__HAL_UART_DISABLE_IT(&huartX, UART_IT_TXE)` 关 TX 中断保护临界区；若发送器空闲（`uart_tx_active == 0`）先把首字节 prime 进 `Instance->TDR`，再 `__HAL_UART_ENABLE_IT(..., UART_IT_TXE)` 重开；
  - ISR：TXE 事件里逐字节取缓冲发送，发完（`uart_tx_n == 0`）自动关 TXE 并清 `uart_tx_active`；
  - 中断初始化：幂等地 `HAL_NVIC_SetPriority(<USART_IRQn>, 5, 0)` + `HAL_NVIC_EnableIRQ(<USART_IRQn>)`。

### 2.2 接线三步

1. 中断向量文件：原 `USARTx_IRQHandler` 走 `Default_Handler`，改为调用日志模块的 TX 中断服务函数（并 include 日志头）。
2. 串口初始化之后调用日志的中断初始化函数；也可在首次写入时懒使能 NVIC 作兜底。
3. 构建脚本注册新的日志源文件。

### 2.3 为什么「关 TX 中断」是对的

- 裸机没有互斥量；TX 环索引被**线程上下文（写入函数）**与**中断上下文（ISR）**共享。唯一正确的临界区是：修改索引期间**禁止 TXE 中断**，使 ISR 无法同时改读指针 / 计数。
- prime 首字节到 `TDR` 必须在重开中断**之前**完成——否则 ISR 可能在 `TDR` 空、索引尚未推进时误读旧数据。首字节写 `TDR` 本身是安全的（`TDR` 空时写入即触发移位输出）。
- **不要**在 ISR 里调日志宏（会重入同一个环）；ISR 只允许执行 TX 中断服务函数。

### 2.4 验收

- Debug 与 Release 双构**均 0 warning**；核对 FLASH / RAM 占用与上一版无意外增长。
- 烧录校验 `Verified OK`；串口（115200 8N1）抓到完整启动 banner，证明 TX 中断驱动的日志在硬件上真实输出。
