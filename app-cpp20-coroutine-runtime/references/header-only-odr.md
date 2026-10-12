# header-only 化：inline / thread_local / ODR 的完整落地

配套 `app-cpp20-coroutine-runtime/SKILL.md` §5。一个原本带 `src/*.cpp` 的协程库改成纯
header-only（CMake **INTERFACE** 库、无 `.a`/`.lib`）时踩过的全部坑，含负向对照命令。

---

## 一、为什么必须有一个**多 TU 可执行文件**

header-only 的漏 `inline` **只会在"两个 TU 同时包含同一个头"时**以链接期"重复符号"暴露。
其余单元测试全是单 TU，**根本测不出来** —— 它们会全绿，然后消费者第一次链接就炸。

所以测试套件里要有**唯一一个**多 TU 可执行文件：

```
tests/
  test_odr_multi_tu.cpp     # 主：包含伞头，定义 main()
  test_odr_partner.cpp      # 伴：包含同一批头，提供另一个 TU 的函数
  multi_tu_api.hpp          # 两个 TU 共享的函数声明（见 §四）
```

它断言的不只是"能链接"，还有**跨 TU 的单例语义**：在 TU-B 的协程里读
`current_scheduler()` / `current_task_id()`，必须与 TU-A 一致。

---

## 二、四条硬约束

| 约束 | 违反后的症状 |
|---|---|
| 每个非模板定义 `inline` | `multiple definition of <sym>` + `first defined here` |
| 线程局部量 `inline thread_local`，放**命名空间**内 | 匿名 namespace 在头里 = **每个 TU 各一份** → `current()` 在别的 TU 读到 `nullptr` |
| 进程级计数器 `inline` 函数局部 `static` | 每 TU 一份 → 泄漏断言恒成立/恒不成立 |
| 头里的 `main()` **不能** `inline` | 标准禁止；只在单 TU 可执行文件里定义 |

### 细节说明

- **匿名 namespace 是陷阱中的陷阱。** 原来 `scheduler.cpp` 里写
  `namespace { thread_local Scheduler* tls_current_scheduler; }` 是**正确的**
  （一个 .cpp 一个 TU，一份实例）。把它整体搬进头文件后，就变成**每个包含者各一份**。
  正解：搬进具名命名空间 + `inline`：
  ```cpp
  namespace cppcoroutine { namespace detail {
  inline thread_local Scheduler* tls_current_scheduler = nullptr;
  inline thread_local TaskId       tls_current_task      = kInvalidTaskId;
  }}
  ```
- **函数局部 `static` + `inline` 函数 = 全程序一份。** 进程级计数器用这个写法：
  ```cpp
  inline Counters& global_counters() { static Counters c{}; return c; }
  ```
  这是 header-only 下**唯一**能保有"单例"语义的可靠写法。绝不要写成
  `inline Counters g_counters;`（那也会是一份，但把静态初始化顺序问题引进来了）。
- **`main()` 的处理**：`test_framework.hpp` 在头里提供 `main()`，因此它必须只在
  **单 TU 可执行文件**里被定义，并给"自带 main"的用例留退让开关：
  ```cpp
  #ifndef CPPCOROUTINE_TEST_NO_MAIN
  int main(int argc, char** argv) { return run_all_tests(argc, argv); }
  #endif
  ```
  注意 `main` 加 `inline` 是**标准禁止**的（[basic.start.main]）。

---

## 三、CMake：INTERFACE 库

```cmake
add_library(cppcoroutine INTERFACE)
add_library(CppCoroutine::CppCoroutine ALIAS cppcoroutine)

target_include_directories(cppcoroutine
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>)

set_target_properties(cppcoroutine PROPERTIES
    INTERFACE_POSITION_INDEPENDENT_CODE ON)

# 把公共头列为 INTERFACE 源，让 IDE 可见、安装规则能拾取（可选但推荐）
target_sources(cppcoroutine INTERFACE ${CPPCOROUTINE_PUBLIC_HEADERS})
```

**给 INTERFACE 库设编译选项必须用 `INTERFACE` 作用域** —— `PRIVATE` 用在 INTERFACE 库上
CMake 直接报错。若有个共用的 `apply_strict_warnings(target)` 辅助函数，要能按目标类型选作用域：

```cmake
function(_scope_prefix target out)
  get_target_property(t ${target} TYPE)
  if (t STREQUAL "INTERFACE_LIBRARY")
    set(${out} INTERFACE PARENT_SCOPE)
  else()
    set(${out} PRIVATE PARENT_SCOPE)
  endif()
endfunction()
```

### 编译器条件要按 **ID**，不要按"非 MSVC"

曾经的缺陷：`else()` 分支把 GCC 专属警告（`-Wduplicated-cond`、`-Wduplicated-branches`、
`-Wlogical-op`）无条件加给所有非 MSVC 编译器。Clang 会报 `-Wunknown-warning-option`，
在 `-Werror` 下变成**硬编译失败** —— 于是 README 里"Clang 14+"的支持声明实际不成立。

```cmake
if(MSVC)
  ...
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
  target_compile_options(${t} ${scope} -Wduplicated-cond -Wduplicated-branches -Wlogical-op)
endif()
```

静态链接选项只在 MinGW 生效，别泄漏到 Linux：
`if(NOT MSVC AND MINGW) ... -static-libgcc -static-libstdc++ -static ... endif()`。

---

## 四、负向对照：证明"多 TU 测试有牙齿"

**做法**：临时去掉一个"肯定会被多个 TU 引用"的成员函数的 `inline`，重新构建多 TU 目标。

```bash
# 1) 临时去掉 inline（只做验证，不要提交）
#    scheduler.hpp:  inline void Scheduler::run()  ->  void Scheduler::run()
cmake --build build --target app_odr_multi_tu
```

**期望报错（这就是"有牙齿"的证据）**：

```
multiple definition of `cppcoroutine::Scheduler::run()'
CMakeFiles/app_odr_multi_tu.dir/tests/test_odr_multi_tu.cpp.obj:... first defined here
CMakeFiles/app_odr_multi_tu.dir/tests/test_odr_partner.cpp.obj:... first defined here
collect2.exe: error: ld returned 1 exit status
```

**验证完必须恢复 `inline`**，并在提交前 grep 复核（别把实验状态提交进去）：

```bash
grep -n "inline void Scheduler::run" include/cppcoroutine/scheduler.hpp
```

### 纯头文件独立编译实测（可选但便宜）

证明"消费者真的不需要库文件"：

```bash
g++ -std=c++20 -O2 -Iinclude quickstart.cpp -pthread -o quickstart   # 无 -l，无 .a
./quickstart
```

---

## 五、`-Wmissing-declarations`（GCC 15 起对 C++ 生效）

**现象**：多 TU 夹具里，**非 `inline` 的外部链接函数定义**全部报
`-Werror=missing-declarations`；`inline` / 模板 / 内部链接函数不报。

**结论**：库侧全 `inline` **恰好天然免疫**；需要跨 TU 共享的函数必须**先有声明**。
给夹具补一个声明头即可：

```cpp
// tests/multi_tu_api.hpp
#pragma once
namespace odr_probe {
int  partner_value();     // 在 test_odr_partner.cpp 里定义
void partner_bump();
}
```

---

## 六、改造成 header-only 的检查清单

- [ ] 删除整个 `src/`；实现并入公共头，逐个加 `inline`。
- [ ] 匿名 namespace 的 `thread_local` / 全局量 → **具名 namespace + `inline thread_local`**。
- [ ] 单例/计数器 → `inline` 函数局部 `static`。
- [ ] `CMakeLists.txt` → `add_library(... INTERFACE)` + `INTERFACE_POSITION_INDEPENDENT_CODE`；
      严格警告辅助函数按目标类型选 `INTERFACE`/`PRIVATE` 作用域。
- [ ] 新增多 TU 可执行文件 + `*_api.hpp` 声明头。
- [ ] 跑负向对照（去 `inline` → 应链接失败），确认后**恢复**。
- [ ] 纯头文件独立编译实测（`-Iinclude` 且无 `-l`）。
- [ ] Debug/Release **双构零警告**；`ctest` 全绿（含新增的多 TU 用例）。
- [ ] 文档同步：说明"代价是编译时间 —— 大 TU 用窄头（`scheduler.hpp`）而非伞头"。

---

## 七、附带的一个真实 flaky（改造前就存在的缺陷）

`FramesStayBalancedUnderRepeatedCancellation` 用 **1 ms 回调探针**断言
`waiting_task_count() == 200`。但 200 对"即时父子任务"需要 600 次循环迭代，Debug 下本身
就 > 1 ms，探针会提前触发（实测读到 288）→ 约 **1/18 概率**失败。

**修法（完全确定性，不用挂钟）**：两阶段 + 就绪队列触发器。
阶段 1 先 `run()` 让 400 个父子任务确定性跑完；阶段 2 spawn 200 个睡 10 s 的挂起者 +
**最后** spawn 一个"取消触发器" —— 靠就绪队列 FIFO 保证它在全部 200 个 park 之后才被调度
⇒ `waiting_task_count()` 精确等于 200。

断言同步更新为 `tasks_cancelled == 201`（200 挂起者 + 触发器自身，因为 `cancel_all()` 会取消
调用者）、`tasks_completed == 400`。**验证：连续 40 次全绿**（修复前 18 次里必错 1 次）。
这类修法的要点是：**把"等时间"换成"等事件顺序"**。
