---
name: mcu-cpp-development
description: 用 C++ 写单片机：C/C++ 混合链接与 extern "C"、模板+constexpr 零成本外设封装、new/delete 重载、Makefile 双编译。症状：undefined reference 到重载函数。
agent_created: true
---

# 用 C++ 开发单片机：方法与代码格式

C++ 在 MCU 上的定位：**库层（HAL / RTOS / LVGL / LwIP / TinyUSB）继续用 C，外设驱动与应用层用 C++ 封装**。
收益是零成本抽象与类型安全；代价是必须显式处理**链接、内存、模板膨胀**三件事。
配套 `stm32-build-and-scaffold`（构建骨架）、`mcu-code-style`（C 代码规范：静态状态封装与注释）、`stm32-peripherals-and-memory`（外设判据）。

## 何时用

- 决定"该不该上 C++"、MCU 上 C++ 子集怎么选、编译开关怎么定。
- 写 `.hpp` 驱动层（GPIO/I2C/DAC 那类模板类）、`.cpp` 应用层、ISR 桥接。
- 报错 `undefined reference to 'foo(int)'`（链接名被 mangle）、`new` 未定义、体积暴涨。
- 移植 RTOS 下的 `new/delete`，或要做内存占用统计。

完整可编译范例见 `references/cpp-on-mcu-patterns.md`（GPIO 四段式 / I2C 双层继承 / MEM_ALLOC 全集 / 构建验证清单）。

---

## 一、分工边界

| 层 | 语言 | 理由 |
|---|---|---|
| HAL / CMSIS / RTOS / 中间件（LVGL、LwIP、TinyUSB、FatFs） | **C** | 官方只提供 C，改动即失去可升级性 |
| 外设驱动封装（`driver/*.hpp`）、器件驱动（传感器、屏） | **C++** | 模板元编程 + RAII，编译期确定，零运行时开销 |
| 应用逻辑（`application/*.cpp`）、`main`、任务体 | **C++** | 类 + 命名空间组织，接口返回枚举而非错误码宏 |
| 启动文件 `.s`、`system_*.c`、`syscalls.c`、HAL 回调与中断向量 | **C** | 工具链/厂商生成，保持 ABI 原样 |

**判据**：只有"厂商提供的、会被整体替换的"才留在 C。不要为统一而重写 HAL，也不要往中断向量表里塞 C++ 语义。

---

## 二、混合编程的三个接口契约

### 1. 被 C 包含的头必须带 `extern "C"` 守卫

```c
#ifdef __cplusplus
extern "C" {
#endif
#include "stm32f4xx_hal.h"
void get_info_total(void);
#ifdef __cplusplus
}
#endif
```

⚠️ `#include` 放守卫**里**还是**外**两种做法都有代价，**同工程统一选一种，不要混用**——
混用会出现"部分函数按 C 链接、部分按 C++ 链接"的间歇性 `undefined reference`。

### 2. 单函数桥接：`extern "C"` 写在定义处

```cpp
class INFO { public: int a; int b; };
INFO info = {0};
extern "C" int get_info_total(void) { return info.a + info.b; }   // 链接名即 get_info_total
```

**典型用途：HAL 弱回调与 ISR**。推荐写法是 **C 侧 ISR → 转发给 C++ 对象方法**，不在 C++ 里直接实现 ISR。
若反过来在 C++ 里写 ISR，**必须** `extern "C"`，否则向量表按 mangle 名找不到符号，
表现是**中断不进且无任何报错**（最难查的静默故障之一）。

### 3. mangle 规则要能背下来

| 声明 | C 链接名 | C++ 链接名 |
|---|---|---|
| `int foo(int)` | `foo` | `_Z3fooi` |
| `int foo(float)` | 不支持重载 | `_Z3foof` |
| `int foo(int,int)` | — | `_Z3fooii` |

**判据**：报 `undefined reference to '_Z3fooi'` → 定义方漏 `extern "C"`；
报 `undefined reference to 'foo'` → 调用方在 C++ 里没看到 C 声明（漏包含带守卫的头）。

---

## 三、驱动封装格式：模板 + `if constexpr` 编译期派发

核心产出物。**目标：把"运行时查表/分支"变成"编译期定值"，实例化后的机器码与手写 C 等价。**

四段式（完整代码见 references）：

```cpp
enum class RT_CXX_TYPE { RT_OK = 0, RT_FAIL = -1, RT_TIMEOUT = -2, RT_NOINIT = -3 };

namespace stm32f4 { namespace gpio {
enum class GPIO_PORT { PA = 0, PB, PC, PD, PE, PF, PG, PH };              // ① enum class 而非 #define

template<GPIO_PORT port> constexpr GPIO_TypeDef* GPIO_PORT_TO_ADDR(void){ // ② 编译期映射
    if constexpr (port == GPIO_PORT::PA) return GPIOA;
    else if constexpr (port == GPIO_PORT::PB) return GPIOB; /* ... */ else return nullptr;
}

template <GPIO_PORT port, int pin> class device_gpio {                    // ③ 配置全作模板参数
    static_assert(pin >= GPIO_PIN_0 && pin <= GPIO_PIN_15, "pin number not support");
protected:
    GPIO_TypeDef* port_{GPIO_PORT_TO_ADDR<port>()};
    int pin_num_{pin};
public:
    RT_CXX_TYPE init(uint32_t mode, uint32_t pull = GPIO_NOPULL, /* ... */)
    { /* 填 GPIO_InitTypeDef → HAL_GPIO_Init */ return RT_CXX_TYPE::RT_OK; }
};

template <GPIO_PORT port, int pin>                                        // ④ 能力用继承细分
class DEV_GPIO_OUTPUT : public device_gpio<port, pin> {
public:
    void toggle() { HAL_GPIO_TogglePin(this->port_, this->pin_num_); }
}; }}

// 使用侧（顶层 static 对象，无动态分配）
using namespace stm32f4::gpio;                             // using 只在 .cpp 里
static DEV_GPIO_OUTPUT<GPIO_PORT::PB, GPIO_PIN_0> led;     // 引脚写进类型，不可能传错端口
```

### 四条格式铁律

1. **外设信息一律编码进模板参数**（端口/引脚/通道/复用），`init()` 只接收运行期才知道的（速率、触发源、极性）。
   模板参数能 `static_assert` 校验，函数参数不能。
2. **每层具名空间隔离**：`namespace <系列> { namespace <外设> { ... } }`，避免与 HAL 撞名。
3. **初始化返回 `RT_CXX_TYPE` 枚举**，不返回 `bool`（丢原因）、不返回 HAL 状态码（泄漏厂商类型）。
4. **对象声明为文件级 `static`**，不用 `new`、不用单例宏。

### ⚠️ 两个实测坑（写新代码时避开）

**坑 1 —— `init()` 把失败码写成了成功码**（`driver/dac.hpp`）：最后一行 `return RT_CXX_TYPE::RT_FAIL;`
导致 `if (dac1.init() != RT_OK) return;` **永远进不去错误分支**，初始化失败被静默吞掉。
编译零警告。**新写 `init()` 时逐一核对每条返回路径，最后一行必须是 `return RT_OK`。**

**坑 2 —— GPIO 时钟使能散落在驱动 `init()` 里**：同端口多个引脚会重复使能（HAL 宏带 `IS_RCC` 保护，不报错但难审计）。
**外设时钟（I2C/DAC/SPI）应在 `HAL_xxx_Init()` 之前、由板级 `bsp_clock_init()` 集中打开一次；
驱动 `init()` 只配置不使能。**

### 传输层 + 器件层双层继承（标准范式）

- **传输层**（`device_i2c<mode, method>`）：模板参数选硬件实例与主从，`init(clock_speed, dutycycle)` 传入运行期量。
  必维护 `bool is_init`，**所有收发方法首行检查**并返回 `RT_NOINIT`——这是"忘了调 init"唯一能在编码期兜住的点，
  否则表现为总线无响应，与硬件接线错误无法区分。
- **器件层**（`device_ap3216<mode>`）：继承传输层，私有方法只写寄存器语义；
  器件地址左移 1 位的 HAL 格式收敛在私有 `read_reg/write_reg` 里，不泄漏到业务代码。
  换总线只改一个模板参数。统一暴露 `get_info()` 返回内部结构体指针，避免宿主循环里值拷贝。
- **HAL 句柄聚合初始化置零**（`I2C_HandleTypeDef s{0};`），不在 `init()` 里 `memset`——
  `Lock`/`State` 残留脏值会让后续 HAL 调用返回 `HAL_BUSY`。
- **`set_value` 之类接口用物理量（mV）作参数**，内部转码值并饱和钳位——
  单位与量程的约束收敛到类内，这是 C++ 封装相对 C 宏的真实收益。

---

## 四、`new/delete` 重载

MCU 上默认 `new` 走 newlib `malloc`（线程不安全、有碎片、无法统计）。上 RTOS 后重载导向 `pvPortMalloc`：

```cpp
class MEM_ALLOC {
private:
    inline static size_t mem_size = 0;            // C++17：类内定义，无需类外再写一遍
public:
    static void *new_without_throw(size_t size) noexcept {
        void *pT = pvPortMalloc(size);
        if (pT == NULL) return nullptr;
        taskENTER_CRITICAL(); mem_size += size; taskEXIT_CRITICAL();
        return pT;
    }
    void *operator new(size_t size)                                  { return new_with_throw(size); }
    void *operator new[](size_t size)                                { return new_with_throw(size); }
    void *operator new(size_t size, const std::nothrow_t&) noexcept  { return new_without_throw(size); }
    void operator delete(void *ptr, size_t size)   { delete_ptr(ptr, size); }
    void operator delete[](void *ptr, size_t size) { delete_ptr(ptr, size); }
    static size_t get_size() { return mem_size; }
};
```

- `#include <new>` **必须显式加**（`std::bad_alloc` / `std::nothrow_t` 在此头里）。
- 目标类**公有继承 `MEM_ALLOC`**，`operator new` 才会被该类作用域查到。
- **MCU 上统一用 `new (std::nothrow)` + 判空**（`-fno-exceptions` 下 `throw` 版本不可用）。
- **需要精确统计的类必须显式声明析构函数**（哪怕空 `~INFO() {}`）——
  否则编译器可能调用无 `size_t` 的 delete 版本，统计无法更新。
- `inline static` 是 C++17；C++11/14 下改类外定义（`size_t MEM_ALLOC::mem_size = 0;`，只能一处）。
- **更需要警惕"根本不该 new"**：裸机全 `static`，RTOS 用 `xTaskCreateStatic`/静态队列。
  重载只是给"确实需要动态生命周期"的场景兜底，不是鼓励用堆。
- 系统调用垫片 `_sbrk` 撑起的 newlib heap 与这里重载的 RTOS 堆是**两个互不相干的池子**，不要混谈。

---

## 五、MCU 上的 C++ 子集：编译开关怎么定

| 特性 | 建议 | 理由 |
|---|---|---|
| 类 / 继承 / 命名空间 / 引用 | ✅ 放开 | 零运行时开销 |
| 模板 + `constexpr` + `if constexpr` | ✅ 鼓励 | 编译期派发，取代运行期查表 |
| `enum class` / `static_assert` / `inline static` | ✅ 鼓励 | 强类型、编译期校验、免类外定义 |
| 异常 `throw`/`try` | ❌ `-fno-exceptions` | 体积与栈回卷代价高，MCU 无法可靠恢复 |
| RTTI `dynamic_cast`/`typeid` | ❌ `-fno-rtti` | 虚表膨胀，驱动层不需要运行时类型识别 |
| 虚函数 | ⚠️ 慎用 | 仅统一设备接口级多态用；单层驱动用模板 |
| STL 容器 / `iostream` / `std::function` | ❌ 禁 | 动态分配 + 体积膨胀 |
| 多重继承 / 虚继承 | ❌ 禁 | 对象布局与指针调整代价 |

```cmake
target_compile_options(${PROJECT_NAME} PRIVATE
    -std=c++17
    -fno-exceptions -fno-rtti -fno-threadsafe-statics -fno-use-cxa-atexit
    -fno-unwind-tables -fno-asynchronous-unwind-tables)
```

- `-fno-threadsafe-statics`：关掉函数局部 `static` 的线程安全守卫（会引入 `__cxa_guard_acquire`）。
  裸机安全；**RTOS 下若多任务里首次构造同一局部 static，需评估后再定**。
- `-fno-use-cxa-atexit`：省全局对象析构注册。
- **后缀规则：`.h` 给 C 编译器看的头，`.hpp` 给 C++ 用的头**。绝不用 `.h` 装模板类。

---

## 六、Makefile 双编译规则

C 与 C++ **用不同编译器、不同标志集，但共用同一份 include 路径与规则模式**：

```makefile
CC      := $(CROSS_COMPILE)gcc
CCPLUS  := $(CROSS_COMPILE)g++

CPLUSFLAGS := $(CPU_FLAGS) $(OPTIONS_FLAG) -fdata-sections -ffunction-sections -MMD -MP -std=c++17 \
              -fno-exceptions -fno-rtti -fno-threadsafe-statics -fno-use-cxa-atexit

OBJECTS  = $(C_APP_SOURCES:.c=.o)
OBJECTS += $(CPP_APP_SOURCES:.cpp=.o)      # 两个源集分别映射再合并
OBJECTS += $(ASM_SOURCES:.s=.o)

%.o: %.c
	$(CC) -c $(CFLAGS) $(C_INCLUDES) $< -o $@
%.o: %.cpp
	$(CCPLUS) -c $(CPLUSFLAGS) $(C_INCLUDES) $< -o $@

$(TARGET): $(OBJECTS)
	$(CC) $(OBJECTS) $(LINKFLAGS) -o $(TARGET).elf      # ← 用 gcc 链接，不是 g++
```

- **链接用 `gcc`**：`g++` 会自动带 libstdc++，对不用 STL/异常/RTTI 的工程是纯增重；
  用 `gcc` 链接能强制暴露"是否真的依赖了 C++ 运行时"。
  **但若工程真的用了 libstdc++（如 `throw`），必须改 `g++` 链接或显式 `-lstdc++`。**
- `-MMD -MP` 给 `.cpp` 也生成 `.d`，头文件改动能触发重编。
- 新增 `.cpp` 目录要同步加进 `CPP_APP_SOURCES` 的 wildcard。

---

## 七、应用层格式约定

```cpp
#include "includes.h"          // C 侧头（已带 extern "C" 守卫）
#include "gpio.hpp"
using namespace stm32f4::gpio; // 只在 .cpp 里 using

static DEV_GPIO_OUTPUT<GPIO_PORT::PB, GPIO_PIN_0> led;

RT_CXX_TYPE driver_init(void) {
    RT_CXX_TYPE type;
    type = led.init(GPIO_MODE_OUTPUT_PP);
    if (type != RT_CXX_TYPE::RT_OK) return type;      // 逐项检查，失败立即返回
    return type;
}

int main(void) {
    HAL_Init(); logger_module_init(); driver_init();
    auto info_ptr = ap3216c.get_info();               // 取内部指针，主循环不重复访问器调用
    while (1) { /* ... */ led.toggle(); HAL_Delay(500); }
}
```

- **`using namespace` 只出现在 `.cpp`**，写进 `.hpp` 会污染所有包含者（尤其 HAL 头）。
- 驱动初始化**逐项检查返回码并立即返回**，不做"失败了继续跑"的容错。
- `.cpp` 顶层只放常量与对象定义，算法进类方法。

---

## 八、常见报错对照

| 现象 | 根因 | 修法 |
|---|---|---|
| `undefined reference to '_Z3fooi'` | 定义在 `.cpp`，调用方按 C 找符号 | 定义处加 `extern "C"` |
| `undefined reference to 'foo'` | C++ 调用方没看到 C 声明 | 头文件加守卫并包含 |
| `undefined reference to 'operator new(unsigned int)'` | 用了 `new` 但没重载，heap 为 0 | 继承 `MEM_ALLOC` 或改静态对象 |
| `undefined reference to '__cxa_atexit'` | 全局对象析构注册 | 加 `-fno-use-cxa-atexit` |
| `undefined reference to '__gxx_personality_v0'` | 开了异常但没链 libstdc++ | 加 `-fno-exceptions`（推荐）或改 `g++` 链接 |
| 中断不进且无报错 | C++ 里写 ISR 没加 `extern "C"` | ISR 写 C 侧转发，或加 `extern "C"` |
| Flash 体积暴涨 | 用了 STL/`iostream`/异常/RTTI | 按第五节表格关闭 |
| `static_assert` 报 `pin number not support` | 引脚常量写错 | 改模板参数 |

**验证**：`arm-none-eabi-nm --undefined-only $(TARGET).elf | grep -i cxa` 出现 `__cxa_*`
说明异常/RTTI/atexit 没关干净。同功能 C 与 C++ 实现体积差应 < 5%（模板全编译期展开时通常完全相等）。

---

## 反模式速查

| 反模式 | 后果 | 正确做法 |
|---|---|---|
| `.hpp` 里写 `using namespace` | 污染包含者，易与 HAL 冲突 | 只在 `.cpp` 里 using |
| `init()` 末尾 `return RT_FAIL` | 初始化失败被静默吞掉 | 核对每条返回路径 |
| 错误判断写 `!= RT_FAIL` | 引入多返回码后彻底失效 | 统一写 `!= RT_OK` |
| 用 `bool` 返回驱动初始化结果 | 丢失失败原因 | 返回 `RT_CXX_TYPE` 枚举 |
| 类里 `new` 分配内部缓冲 | 碎片 + 无统计 + 线程不安全 | 成员数组或继承 `MEM_ALLOC` |
| 驱动对象跨单元 `extern` 共享 | 初始化顺序不确定 | 各自 `static` + 显式 `init()` |
| 模板参数塞运行期才知的量 | 实例爆炸（每个取值一份代码） | 运行期量走函数参数 |

## 详细资料

- `references/cpp-on-mcu-patterns.md` — 完整可编译范例：GPIO 四段式、I2C 双层继承、
  DAC 通道编译期映射、`extern "C"` 三种用法对照、`MEM_ALLOC` 全集与接入步骤、
  构建验证清单、本工程源码索引。
- 构建骨架与 Keil 移植：`stm32-build-and-scaffold`。
- C 代码规范（静态状态封装与注释）：`mcu-code-style`。外设与引脚判据：`stm32-peripherals-and-memory`。
