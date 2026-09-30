# C++ on MCU —— 完整范例与源码索引

配套 `mcu-cpp-development/SKILL.md`。所有代码取自真机验证过的 STM32F429 C++ 工程
（STM32F429IGT6 / arm-none-eabi-g++ / `-std=c++17`），可直接编译运行。

---

## 一、各文件承担的职责（分层索引）

| 文件 | 职责 | 对应 SKILL.md 章节 |
|---|---|---|
| `driver/cxx_common.hpp` | `enum class RT_CXX_TYPE` 统一返回码 | 三 |
| `driver/gpio.hpp` | 模板元编程 + `if constexpr` 编译期派发 + 继承细分能力 | 三 |
| `driver/i2c.hpp` | 传输层驱动：模板参数选实例，运行期参数传入 | 三、七 |
| `driver/ap3216.hpp` | 器件层驱动：继承传输层 + 寄存器语义私有化 | 七 |
| `driver/dac.hpp` | 通道编译期映射（`ch_to_dac_info`） | 三 |
| `application/main.cpp` | 驱动初始化三段式 + 主循环 | 七 |
| `application/includes.h` | C/C++ 共用头 + `extern "C"` 守卫 | 二.1 |
| `application/interrupt.cpp` | `extern "C"` 单函数桥接（C++ 类 + C 链接） | 二.2 |
| `Makefile` | C/C++ 双编译规则 + 用 `gcc` 链接 | 六 |
| `application/global_def.h` | 全局模块/驱动开关宏 | 七 |

---

## 二、GPIO：完整四段式（含编译期 IRQ 映射）

```cpp
// driver/gpio.hpp
#ifndef __GPIO_HPP__
#define __GPIO_HPP__
#include "cxx_common.hpp"

namespace stm32f4 { namespace gpio {

enum class GPIO_PORT { PA = 0, PB, PC, PD, PE, PF, PG, PH };

/* 复用功能三元组：给 I2C/SPI/UART 描述"哪个口、哪个脚、哪个 AF" */
struct pins_alternate_info { GPIO_PORT port; uint32_t pin; uint32_t alternate; };

template<GPIO_PORT port>
constexpr GPIO_TypeDef* GPIO_PORT_TO_ADDR(void) {
    if constexpr (port == GPIO_PORT::PA)      return GPIOA;
    else if constexpr (port == GPIO_PORT::PB) return GPIOB;
    else if constexpr (port == GPIO_PORT::PC) return GPIOC;
    else if constexpr (port == GPIO_PORT::PD) return GPIOD;
    else if constexpr (port == GPIO_PORT::PE) return GPIOE;
    else if constexpr (port == GPIO_PORT::PF) return GPIOF;
    else if constexpr (port == GPIO_PORT::PG) return GPIOG;
    else if constexpr (port == GPIO_PORT::PH) return GPIOH;
    else                                      return nullptr;
}

/* 引脚 → EXTI 中断号：同样编译期确定，运行期零开销 */
template<int pin>
constexpr int GPIO_PIN_TO_IRQn(void) {
    if constexpr (pin == GPIO_PIN_0)      return EXTI0_IRQn;
    else if constexpr (pin == GPIO_PIN_1) return EXTI1_IRQn;
    else if constexpr (pin == GPIO_PIN_2) return EXTI2_IRQn;
    else if constexpr (pin == GPIO_PIN_3) return EXTI3_IRQn;
    else if constexpr (pin == GPIO_PIN_4) return EXTI4_IRQn;
    else if constexpr (pin >= GPIO_PIN_5  && pin <= GPIO_PIN_9)  return EXTI9_5_IRQn;
    else if constexpr (pin >= GPIO_PIN_10 && pin <= GPIO_PIN_15) return EXTI15_10_IRQn;
}

template <GPIO_PORT port, int pin>
class device_gpio {
    static_assert(pin >= GPIO_PIN_0 && pin <= GPIO_PIN_15, "pin number not support");
protected:
    GPIO_TypeDef* port_{GPIO_PORT_TO_ADDR<port>()};
    int pin_num_{pin};
public:
    RT_CXX_TYPE init(uint32_t mode, uint32_t pull = GPIO_NOPULL,
                     uint32_t speed = GPIO_SPEED_FREQ_MEDIUM, uint32_t alternate = 0)
    {
        GPIO_InitTypeDef GPIO_InitStruct = {0};
        GPIO_InitStruct.Mode = mode;      GPIO_InitStruct.Pull = pull;
        GPIO_InitStruct.Speed = speed;    GPIO_InitStruct.Pin = pin_num_;
        GPIO_InitStruct.Alternate = alternate;
        HAL_GPIO_Init(port_, &GPIO_InitStruct);
        return RT_CXX_TYPE::RT_OK;
    }
};

template <GPIO_PORT port, int pin>
class DEV_GPIO_OUTPUT : public device_gpio<port, pin> {
public:
    void high()   { HAL_GPIO_WritePin(this->port_, this->pin_num_, GPIO_PIN_SET); }
    void low()    { HAL_GPIO_WritePin(this->port_, this->pin_num_, GPIO_PIN_RESET); }
    void toggle() { HAL_GPIO_TogglePin(this->port_, this->pin_num_); }
};

template <GPIO_PORT port, int pin>
class DEV_GPIO_INPUT : public device_gpio<port, pin> {
public:
    int data() { return HAL_GPIO_ReadPin(this->port_, this->pin_num_) == GPIO_PIN_SET ? 1 : 0; }
};

template <GPIO_PORT port, int pin>
class DEV_GPIO_EXIT : public DEV_GPIO_INPUT<port, pin> {
public:
    void config_irq(int pre_priority = 0, int sub_priority = 0) {
        IRQn_Type IRQn = GPIO_PIN_TO_IRQn<pin>();
        HAL_NVIC_SetPriority(IRQn, pre_priority, sub_priority);
        HAL_NVIC_EnableIRQ(IRQn);
    }
};

}}
#endif
```

**设计收益**：
- `DEV_GPIO_OUTPUT<GPIO_PORT::PB, GPIO_PIN_0>` 这个类型本身就是"PB0 输出"的完整描述，传参不可能传错。
- `static_assert` 把非法引脚挡在编译期，而不是运行时 `HAL_GPIO_Init` 静默失败。
- `GPIO_PIN_TO_IRQn<pin>()` 展开后就是常量，编译器直接内联成立即数，无查表。

**注意**：本工程 `device_gpio::init()` 里没有调 `clock_enable<port>()`
（早期版本有，实际时钟在 `HAL_Init` 阶段已开）。**GPIO 时钟应集中在板级初始化，不由驱动对象各自使能**——
因为同一端口的多个引脚会重复使能，虽然 HAL 宏带 `IS_RCC` 保护不会出错，但增加了审计难度。

---

## 三、I2C：传输层 + 器件层双层继承（标准范式）

### 3.1 传输层：模板参数选硬件实例，运行期参数走 `init()`

```cpp
// driver/i2c.hpp（节选）
namespace stm32f4 { namespace i2c {

enum class I2C_METHOD { MASTER = 0, SLAVE };
enum class I2C_MODE {                      // 枚举值 = "实例 + 引脚组合"
    I2C1_PB6_PB7 = 0, I2C1_PB8_PB9,
    I2C2_PB10_PB11,   I2C2_PF1_PF0, I2C2_PH4_PH5,
    I2C3_PH7_PH8,
};

struct i2c_information {
    gpio::pins_alternate_info scl_gpio_;
    gpio::pins_alternate_info sda_gpio_;
};

/* 一次 constexpr 调用同时给出 SCL/SDA 的端口+引脚+AF */
template<I2C_MODE i2c_mode>
constexpr i2c_information convert_to_i2c_info(void) {
    if constexpr (i2c_mode == I2C_MODE::I2C1_PB6_PB7)
        return { {gpio::GPIO_PORT::PB, GPIO_PIN_6, GPIO_AF4_I2C1},
                 {gpio::GPIO_PORT::PB, GPIO_PIN_7, GPIO_AF4_I2C1} };
    else if constexpr (i2c_mode == I2C_MODE::I2C2_PH4_PH5)
        return { {gpio::GPIO_PORT::PH, GPIO_PIN_4, GPIO_AF4_I2C2},
                 {gpio::GPIO_PORT::PH, GPIO_PIN_5, GPIO_AF4_I2C2} };
    /* ... 其余组合 */
}

template<I2C_MODE i2c_mode> I2C_TypeDef *convert_to_i2c(void) {
    if constexpr (i2c_mode == I2C_MODE::I2C1_PB6_PB7 || i2c_mode == I2C_MODE::I2C1_PB8_PB9) return I2C1;
    else if constexpr (i2c_mode == I2C_MODE::I2C2_PH4_PH5) return I2C2;
    else if constexpr (i2c_mode == I2C_MODE::I2C3_PH7_PH8) return I2C3;
}

template<I2C_MODE i2c_mode> void i2c_clock_enable(void) {
    if constexpr (/* I2C1 的任一组合 */) __HAL_RCC_I2C1_CLK_ENABLE();
    else if constexpr (/* I2C2 的任一组合 */) __HAL_RCC_I2C2_CLK_ENABLE();
    else if constexpr (/* I2C3 */) __HAL_RCC_I2C3_CLK_ENABLE();
}

template<I2C_MODE i2c_mode, I2C_METHOD method = I2C_METHOD::MASTER>
class device_i2c {
public:
    RT_CXX_TYPE init(uint32_t clock_speed, uint32_t dutycycle = I2C_DUTYCYCLE_2)
    {
        constexpr auto info = convert_to_i2c_info<i2c_mode>();

        gpio::device_gpio<info.scl_gpio_.port, info.scl_gpio_.pin> scl;
        scl.init(GPIO_MODE_AF_OD, GPIO_NOPULL, GPIO_SPEED_FREQ_VERY_HIGH, info.scl_gpio_.alternate);
        gpio::device_gpio<info.sda_gpio_.port, info.sda_gpio_.pin> sda;
        sda.init(GPIO_MODE_AF_OD, GPIO_NOPULL, GPIO_SPEED_FREQ_VERY_HIGH, info.sda_gpio_.alternate);

        i2c_clock_enable<i2c_mode>();

        i2c_struct_.Instance = i2c_port_;
        i2c_struct_.Init.ClockSpeed = clock_speed;
        i2c_struct_.Init.DutyCycle  = dutycycle;
        if constexpr (method == I2C_METHOD::SLAVE) {
            i2c_struct_.Init.AddressingMode  = I2C_ADDRESSINGMODE_7BIT;
            i2c_struct_.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
            i2c_struct_.Init.OwnAddress2     = 0;
            i2c_struct_.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
            i2c_struct_.Init.NoStretchMode   = I2C_NOSTRETCH_DISABLE;
        }
        if (HAL_I2C_Init(&i2c_struct_) != HAL_OK) return RT_CXX_TYPE::RT_FAIL;
        if (HAL_I2CEx_ConfigAnalogFilter(&i2c_struct_, I2C_ANALOGFILTER_ENABLE) != HAL_OK)
            return RT_CXX_TYPE::RT_FAIL;
        if (HAL_I2CEx_ConfigDigitalFilter(&i2c_struct_, 0) != HAL_OK) return RT_CXX_TYPE::RT_FAIL;

        is_init = true;
        return RT_CXX_TYPE::RT_OK;
    }

    /* 每个对外方法都先查 is_init —— 解决"忘了调 init 就收发"这类静默故障 */
    RT_CXX_TYPE mem_read(uint16_t DevAddress, uint16_t MemAddress, uint16_t MemAddSize,
                         uint8_t *pData, uint16_t Size, uint32_t Timeout)
    {
        if (!is_init) return RT_CXX_TYPE::RT_NOINIT;
        if (HAL_I2C_Mem_Read(&i2c_struct_, DevAddress, MemAddress, MemAddSize,
                             pData, Size, Timeout) != HAL_OK)
            return RT_CXX_TYPE::RT_FAIL;
        return RT_CXX_TYPE::RT_OK;
    }
    /* mem_write / device_read / device_write 同构，略 */

private:
    bool is_init{false};
    I2C_TypeDef *i2c_port_{convert_to_i2c<i2c_mode>()};
    I2C_HandleTypeDef i2c_struct_{0};
};

}}
```

**两条可复用的格式约定**：

1. **`is_init` 卫兵 + `RT_NOINIT`**：传输层基类必须维护 `is_init`，所有收发方法首行检查。
   这是"忘了初始化"这类故障唯一能在编码期兜住的点——否则表现为总线无响应，与硬件接线错误无法区分。
2. **`memset` 归零**：`I2C_HandleTypeDef i2c_struct_{0};` 用聚合初始化置零，
   不要在 `init()` 里再 `memset`。HAL 句柄里 `Lock`/`State` 字段残留脏值会导致后续 HAL 调用返回 `HAL_BUSY`。

### 3.2 器件层：继承传输层，只写寄存器语义

```cpp
// driver/ap3216.hpp（节选）
#pragma once
#include "i2c.hpp"

#define AP3216C_ADDR     0x1e
#define AP3216C_TIMEOUT  10
#define AP3216C_SYSTEMCONG 0x00
#define AP3216C_IRDATALOW  0x0A
/* ... 其余寄存器 */

typedef struct { uint16_t ir; uint16_t als; uint16_t ps; } ap3216c_info_t;

/* 模板参数只有一个：挂在哪个 I2C 上。换总线只改这一个参数 */
template<stm32f4::i2c::I2C_MODE mode>
class device_ap3216 : public stm32f4::i2c::device_i2c<mode, stm32f4::i2c::I2C_METHOD::MASTER>
{
    using device_i2c_info_t = stm32f4::i2c::device_i2c<mode, stm32f4::i2c::I2C_METHOD::MASTER>;
public:
    ap3216c_info_t *get_info() { return &info_; }   // 暴露内部数据指针，避免宿主循环里值拷贝

    RT_CXX_TYPE init(uint32_t clock_speed, uint32_t dutycycle, uint8_t mod)
    {
        device_i2c_info_t::init(clock_speed, dutycycle);      // 先初始化传输层
        if (write_reg(AP3216C_SYSTEMCONG, 0x40) != RT_CXX_TYPE::RT_OK) return RT_CXX_TYPE::RT_FAIL;
        HAL_Delay(10);                                        // 软复位等待
        if (write_reg(AP3216C_SYSTEMCONG, mod)  != RT_CXX_TYPE::RT_OK) return RT_CXX_TYPE::RT_FAIL;
        return RT_CXX_TYPE::RT_OK;
    }

    RT_CXX_TYPE read_block()
    {
        uint8_t buf[6];
        for (uint8_t i = 0; i < 6; i++) {
            if (read_reg(AP3216C_IRDATALOW + i, &buf[i]) != RT_CXX_TYPE::RT_OK)
                return RT_CXX_TYPE::RT_FAIL;
        }
        info_.ir  = (buf[0] & (1 << 7)) ? 0 : (((uint16_t)buf[1] << 2) | (buf[0] & 0x03));
        info_.als = ((uint16_t)buf[3] << 8) | buf[2];
        info_.ps  = (buf[4] & (1 << 6)) ? 0 : (((uint16_t)(buf[5] & 0x3F) << 4) | (buf[4] & 0x0F));
        return RT_CXX_TYPE::RT_OK;
    }

private:
    RT_CXX_TYPE read_reg(uint8_t reg, uint8_t *data) {
        return this->mem_read(AP3216C_ADDR << 1, reg, 1, data, 1, AP3216C_TIMEOUT);
    }
    RT_CXX_TYPE write_reg(uint8_t reg, uint8_t data) {
        return this->mem_write(AP3216C_ADDR << 1, reg, 1, &data, 1, AP3216C_TIMEOUT);
    }
private:
    ap3216c_info_t info_;
};
```

⚠️ **本工程 `read_block()` 里有个逻辑错误值得引以为戒**：

```cpp
for(index=0; index<6; index++) {
    if(read_reg(AP3216C_IRDATALOW+index, &buf[index]) != RT_CXX_TYPE::RT_FAIL) {  // ❌ 条件反了
        is_read_ok = 0;
        return RT_CXX_TYPE::RT_FAIL;
    }
}
```

判断应该是 `!= RT_CXX_TYPE::RT_OK`。写成 `!= RT_FAIL` 后：成功（返回 `RT_OK`）也会进分支并 return 失败。
**正确的写法是统一用 `!= RT_OK` 作为错误判据**，因为 `RT_OK == 0` 而其余都是负数——
`!= RT_FAIL` 只在"恰好只有一种失败码"时等价，一旦引入 `RT_TIMEOUT`/`RT_NOINIT` 就彻底失效。
**格式约定：全工程错误判断一律写 `!= RT_CXX_TYPE::RT_OK`。**

**器件层写法要点**：
- 器件地址左移 1 位再传给 HAL（`AP3216C_ADDR << 1`）——HAL 的 8 位地址格式。
  把这个偏移收敛在私有的 `read_reg`/`write_reg` 里，不让它泄漏到业务代码。
- 寄存器访问分三层：`read_reg/write_reg`（单字节语义）→ `read/write`（多字节）→ `read_block`（业务语义）。
  新增功能只往上加业务方法，不动底层。
- 数据缓存（`info_`）作为**成员对象**而非指针——静态对象随程序生存，无需管理生命周期。

---

## 四、DAC：通道 → 引脚/外设信息的编译期映射

```cpp
// driver/dac.hpp（节选）
namespace stm32f4 { namespace dac {
#define DAC_REFERENCE_VOL  3300    // mV
#define DAC_MAX_VALUE      4095    // 12-bit

struct dac_info { gpio::GPIO_PORT port_; uint32_t pin_; };

template <uint32_t ch>
constexpr dac_info ch_to_dac_info(void) {
    if constexpr (ch == DAC_CHANNEL_1) return { gpio::GPIO_PORT::PA, GPIO_PIN_4 };
    else                               return { gpio::GPIO_PORT::PA, GPIO_PIN_5 };
}

template<uint32_t ch>
class dac_deivce {                                  // 注意：类名拼写有误（device），保持与工程一致
    static_assert(ch == DAC_CHANNEL_1 || ch == DAC_CHANNEL_2, "dac channel error!");
public:
    RT_CXX_TYPE init(uint32_t trigger = DAC_TRIGGER_NONE,
                     uint32_t output_buffer = DAC_OUTPUTBUFFER_ENABLE)
    {
        constexpr auto info = ch_to_dac_info<ch>();
        gpio::device_gpio<info.port_, info.pin_> gpio_dev;   // 局部临时对象做引脚配置
        gpio_dev.init(GPIO_MODE_ANALOG);

        __HAL_RCC_DAC_CLK_ENABLE();
        hdac_.Instance = DAC;
        if (HAL_DAC_Init(&hdac_) != HAL_OK) return RT_CXX_TYPE::RT_FAIL;

        sConfig.DAC_Trigger = trigger;
        sConfig.DAC_OutputBuffer = output_buffer;
        if (HAL_DAC_ConfigChannel(&hdac_, &sConfig, ch) != HAL_OK) return RT_CXX_TYPE::RT_FAIL;

        return RT_CXX_TYPE::RT_OK;    // ← 原文此处误写为 RT_FAIL，见 SKILL.md 三.坑1
    }

    void set_value(uint32_t mv, uint32_t mode = DAC_ALIGN_12B_R) {
        if (mv > DAC_REFERENCE_VOL) mv = DAC_REFERENCE_VOL;   // 饱和钳位
        uint32_t code = (uint32_t)((float)mv / DAC_REFERENCE_VOL * DAC_MAX_VALUE);
        HAL_DAC_Stop(&hdac_, ch);
        HAL_DAC_SetValue(&hdac_, ch, mode, code);
        HAL_DAC_Start(&hdac_, ch);
    }
private:
    DAC_ChannelConfTypeDef sConfig = {0};   // ⚠️ 需为成员，原文写在 init() 局部（见下）
    DAC_HandleTypeDef hdac_ = {0};
};
}}
```

**要点**：
- `ch_to_dac_info<ch>()` 把"通道 → 引脚"编码进类型系统，`static_assert` 挡住非法通道。
- **`set_value` 用物理量（mV）作参数**，内部转 DAC 码值。调用方不需知道分辨率——
  这是 C++ 封装相对 C 宏的真实收益：单位与量程的约束被收敛到类内。
- 参数**饱和钳位**而非断言失败，因为设定电压越界是正常业务情形。
- **局部临时对象 `gpio_dev` 用于一次性引脚配置**：不需要作为成员常驻，
  这是 RAII 式"构造时配置"的轻量用法。但注意：若该 `init()` 后续可能被重复调用，
  临时对象的构造会重复配置引脚——正常情况下幂等，无害。

---

## 五、`extern "C"` 三种用法对照

### 5.1 头文件守卫（被 C 包含的头）

```c
// application/includes.h
#ifndef _INCLUDES_H
#define _INCLUDES_H
#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f4xx_hal.h"
#include "global_def.h"
#include "logger.h"

void get_info_total(void);     /* 供 C 侧调用 */

#ifdef __cplusplus
}
#endif
#endif
```

### 5.2 单函数桥接（最常用于 ISR 与 HAL 回调）

```cpp
// application/interrupt.cpp
class INFO { public: int a; int b; };
INFO info = {0};

extern "C" int get_info_total(void) { return info.a + info.b; }
```

对应 C 侧：

```c
/* test.c */
int get_info_total(void);
int run_test(void) { return get_info_total(); }
```

**为什么需要**：`get_info_total` 在 C++ 里若不加 `extern "C"`，链接名会是 `_Z14get_info_totalv`，
C 侧按 `get_info_total` 找不到符号。加了之后链接名就是原始名。

### 5.3 ISR 转发模式（推荐做法）

不要在 C++ 里直接实现 ISR。标准做法是 **C 侧 ISR → 调用 C++ 对象方法**：

```cpp
// C++ 侧：中断逻辑封装在类里
namespace bsp {
class button {
public:
    void on_exti_irq() {          /* 真正的中断处理逻辑 */ }
};
extern button g_button;           // 定义在 .cpp 里
}
```

```c
/* application/stm32f4xx_it.c —— C 侧，保持工具链原样 */
void EXTI3_IRQHandler(void)
{
    HAL_GPIO_EXTI_IRQHandler(GPIO_PIN_3);
}

void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)   /* HAL 弱函数，C 链接 */
{
    if (GPIO_Pin == GPIO_PIN_3) {
        bsp_button_on_exti();      /* 转发给 C++ 侧 */
    }
}
```

**注意 HAL 弱回调本身的约束**：`HAL_GPIO_EXTI_Callback` 由 HAL 以 C 链接方式弱定义，
应用侧重写时**签名必须完全一致，且不需要（也不能）加 `extern "C"`** ——
它定义在 `.c` 文件里就自动是 C 链接。若把它写进 `.cpp`，就**必须**加 `extern "C"`，
否则重写不生效（表现为"回调永远不进默认弱实现"）。

---

## 六、`MEM_ALLOC` 完整实现与接入步骤

### 6.1 完整实现

```cpp
// driver/mem_alloc.hpp
#pragma once
#include <cstddef>
#include <new>
#include "FreeRTOS.h"
#include "task.h"

class MEM_ALLOC
{
private:
    inline static size_t mem_size = 0;     // C++17：类内直接定义，无需类外再写一遍

public:
    static void *new_with_throw(size_t size) {
        void *pT = static_cast<void *>(pvPortMalloc(size));
        if (pT == NULL) { std::bad_alloc ba; throw ba; }
        taskENTER_CRITICAL();
        mem_size += size;
        taskEXIT_CRITICAL();
        return pT;
    }

    static void *new_without_throw(size_t size) noexcept {
        void *pT = static_cast<void *>(pvPortMalloc(size));
        if (pT == NULL) return nullptr;
        taskENTER_CRITICAL();
        mem_size += size;
        taskEXIT_CRITICAL();
        return pT;
    }

    void *operator new(size_t size)                        { return new_with_throw(size); }
    void *operator new[](size_t size)                      { return new_with_throw(size); }
    void *operator new(size_t size, const std::nothrow_t&) noexcept { return new_without_throw(size); }

    static void delete_ptr(void *ptr, size_t size) {
        if (ptr != nullptr) {
            vPortFree(ptr);
            taskENTER_CRITICAL();
            mem_size -= size;
            taskEXIT_CRITICAL();
        }
    }

    void operator delete(void *ptr, size_t size)   { delete_ptr(ptr, size); }
    void operator delete[](void *ptr, size_t size) { delete_ptr(ptr, size); }

    static size_t get_size() { return mem_size; }
};
```

### 6.2 接入步骤

1. **`#include <new>` 必须显式加**：`std::bad_alloc` 与 `std::nothrow_t` 在此头里，不包含会报未定义。
2. **目标类继承 `MEM_ALLOC`**（公有继承，否则 `operator new` 不会被该类的作用域查到）：

```cpp
class INFO : public MEM_ALLOC {
public:
    int get_val() { return a; }
private:
    int a{1};
};

int foo(void) {
    INFO *pInfo = new (std::nothrow) INFO;   // ← 用 nothrow 版本
    if (pInfo == nullptr) return 0;
    int val = pInfo->get_val();
    delete pInfo;
    return val;
}
```

3. **`size_t size` 的 delete 版本由编译器自动选择**——当类有非平凡析构函数时，
   编译器会在 `delete p` 处传入对象大小。若类没有析构函数，编译器可能调用无 size 的版本，
   **此时需要额外提供 `operator delete(void*)`，但没有 size 就无法更新统计**。
   → **结论：需要精确统计的类必须显式声明析构函数**（哪怕是空的 `~INFO() {}`）。
4. **`inline static size_t mem_size`** 是 C++17 特性，`-std=c++11/14` 下需改为类外定义：
   `size_t MEM_ALLOC::mem_size = 0;`（写在某个 `.cpp` 里，只能有一处）。
5. **`std::bad_alloc` 需要异常支持**。若编译参数含 `-fno-exceptions`，
   则 `new_with_throw` 无法工作——**MCU 上统一用 `new (std::nothrow)` + 判空**。

### 6.3 何时不该用

- 裸机工程：对象全部 `static`，不用堆。
- RTOS 工程：任务栈、队列、消息全部用 `xTaskCreateStatic` / `xQueueCreateStatic` 静态分配。
- **`new` 重载的正当用途**：确实需要动态生命周期的对象池、协议栈的按需缓冲、
  或第三方 C++ 库内部会 `new` 的场景（此时重载把分配导向 RTOS 堆，避免与 newlib heap 抢内存）。

---

## 七、构建验证清单

新增 C++ 代码后按序核对：

1. `.cpp` 已加入 `CPP_APP_SOURCES` 的 wildcard（或显式列表）。
2. 头文件后缀正确：纯 C++ 头用 `.hpp`，被 C 包含的头用 `.h` 且带 `extern "C"` 守卫。
3. 编译参数含 `-std=c++17`（若用了 `inline static` / `if constexpr` / 结构化绑定）。
4. 链接用 `gcc`（无 STL/异常）或 `g++`（用了 libstdc++）。
5. 检查是否引入意外符号：`arm-none-eabi-nm --undefined-only $(TARGET).elf | grep -i cxa`
   —— 出现 `__cxa_*` 说明异常/RTTI/atexit 没关干净。
6. 对比体积：`arm-none-eabi-size $(TARGET).elf`。同功能 C 与 C++ 实现体积差应 < 5%
   （模板全部编译期展开时通常完全相等）。
7. `-Wall` 零警告，尤其注意 `-Wreturn-type`（`init()` 漏 return 分支）。

---

## 八、反模式速查

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| `.hpp` 里写 `using namespace` | 污染所有包含者，易与 HAL 符号冲突 | 只在 `.cpp` 里 using |
| C++ 里写 ISR 不加 `extern "C"` | 中断不进，无编译错误 | ISR 写 C 侧，或加 `extern "C"` |
| `init()` 末尾 `return RT_FAIL` | 初始化失败被静默吞掉 | 核对每条返回路径 |
| 错误判断写 `!= RT_FAIL` | 引入多返回码后彻底失效 | 统一写 `!= RT_OK` |
| 用 `bool` 返回驱动初始化结果 | 丢失失败原因 | 返回 `RT_CXX_TYPE` 枚举 |
| 类里用 `new` 分配内部缓冲 | 碎片 + 无统计 + 线程不安全 | 成员数组或继承 `MEM_ALLOC` |
| 用 STL `vector`/`string` | 体积暴涨，堆压力 | `std::array` 或 `static` 成员数组 |
| 驱动对象跨编译单元共享（extern） | 初始化顺序不确定 | 各自 `static`，或用显式 `init()` |
| 模板参数塞运行期才知的量 | 实例爆炸（每个取值一份代码） | 运行期量走函数参数 |
