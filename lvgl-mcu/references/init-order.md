# LVGL 初始化顺序与移植陷阱

只管一件事：**LVGL 起来就崩 / 窗口一闪就没** 这类「还没进入业务逻辑就挂」的问题。
适用范围：LVGL v8/v9，PC 模拟器（SDL2）与 MCU 移植。

## 一、铁律：`lv_init()` 永远第一个

**LVGL 的内存池由 `lv_init()` 创建。任何 `lv_disp_drv_register()` / `lv_indev_drv_register()`
都会从该池分配（链表节点等），所以顺序错了必然空指针崩溃。**

### 错误写法（会崩）

```cpp
// app.cpp
if (!lvgl_port::init()) { return false; }   // ← 内部已 lv_disp_drv_register()
lv_init();                                  // ← 太晚了，堆还没建
ui::theme::init();
```

### 正确写法

```cpp
// app.cpp
lv_init();                       // 1. 先建内存池 / TLSF 堆
ui::theme::init();               // 2. 再初始化样式（theme 也可能 malloc）
if (!lvgl_port::init()) { ... }  // 3. 最后才注册 display / indev 驱动
```

### 崩溃特征（便于快速识别）

```
Thread 1 received signal SIGSEGV
0x... search_suitable_block (control=0x0, ...) at lv_tlsf.c:564
#1 block_locate_free (control=0x0, ...)          lv_tlsf.c:770
#2 lv_tlsf_malloc (tlsf=0x0, size=0x10)          lv_tlsf.c:1102
#3 lv_mem_alloc (size=0x10)                      lv_mem.c:132
#4 _lv_ll_ins_head (ll_p=&_lv_disp_ll)           lv_ll.c:71
#5 lv_disp_drv_register (...)                    lv_hal_disp.c:152
#6 lvgl_port::init ()
```

**看 `tlsf=0x0` / `control=0x0` 就是本坑**，不用再往下查。

### 进程退出码的迷惑性

- 真实是 **SIGSEGV**（Bash 里 `$?` = **139**）。
- 但 Git Bash 有时把信号吞掉、只报 `exit 0`，配合「日志停在某一行」看起来像「优雅退出」。
- **判定方法**：量时间（崩溃在 ~1 s 内）+ 跑调试器拿栈。别只看退出码。

```bash
# 一行拿到栈
gdb -batch -ex "run <args>" -ex "bt 25" ./build/bin/app.exe
```

## 二、`LV_TICK_CUSTOM`：不要同时调 `lv_tick_inc()`

`lv_conf.h` 里一旦这样配：

```c
#define LV_TICK_CUSTOM 1
#define LV_TICK_CUSTOM_INCLUDE "app/lvgl_port.h"   // 注意：这里给的是能被 C 解析的头
#define LV_TICK_CUSTOM_SYS_TIME_EXPR (lvgl_port_tick_get_ms())
```

LVGL 就**自己**去读时钟了。此时主循环里**再**调 `lv_tick_inc(elapsed)` = **重复计时**，
定时器会跑飞（动画快一倍、超时提前触发）。

```cpp
while (running) {
    lvgl_port::handleEvents();
    bus_->dispatchPending();
    lv_timer_handler();
    lvgl_port::presentFrame();
    platform::sleepMillis(2);
    // 不要 lv_tick_inc()！LV_TICK_CUSTOM 已经驱动了
}
```

### 关键陷阱：`LV_TICK_CUSTOM_INCLUDE` 指向的头必须能被 **C 编译器**解析

LVGL 的 `.c` 文件会 `#include` 指定的头。若那个头写了 `namespace` / `constexpr` / `extern "C"`，
C 编译直接报 `cstdint: No such file` 之类。**必须写成 C/C++ 双兼容**：

```c
/* lvgl_port.h -- 能被 C 和 C++ 同时包含 */
#ifndef APP_LVGL_PORT_H
#define APP_LVGL_PORT_H

#include <stdint.h>          /* 不是 <cstdint> */

#ifdef __cplusplus
extern "C" {
#endif

uint32_t lvgl_port_tick_get_ms(void);

#ifdef __cplusplus
}   /* extern "C" */
#endif

#ifdef __cplusplus
namespace lvgl_port {
bool init();
void handleEvents();
void presentFrame();
bool isRunning();
}
#endif

#endif
```

同时构建系统要给 LVGL 加**能解析该头路径**的 include：

```cmake
target_include_directories(lvgl PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
```

## 三、SDL2 桌面后端：自己写，别用第三方 SDL 后端

**为什么不用第三方 `lv_drivers` 的 SDL 后端**：它**接管主循环**，
且在窗口关闭时直接 `exit(0)`，绕过应用自身的清理逻辑
（worker 线程、socket、配置落盘都来不及收尾）。

自写 SDL 后端要点：

- `SDL_Init(SDL_INIT_VIDEO)` → `SDL_CreateWindow(..., SDL_WINDOW_SHOWN)`
- **固定分辨率不可缩放**：

  ```cpp
  // 创建时不带 SDL_WINDOW_RESIZABLE
  SDL_SetWindowResizable(win, SDL_FALSE);
  SDL_SetWindowMinimumSize(win, W, H);
  SDL_SetWindowMaximumSize(win, W, H);
  ```

- `SDL_CreateRenderer(win, -1, SDL_RENDERER_SOFTWARE)`；失败再退 `flags=0` 兜底
- `SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, W, H)`
- 帧缓冲在 `init()` 里 `malloc` 并**预填背景色**，避免首帧白闪
- `tickGetMs()` 直接返回 `SDL_GetTicks()`

### CMake 链接 SDL2 的三个坑

```cmake
# 坑 1：不要链接 SDL2main —— 否则要求 main 改名 SDL_main
# 坑 2：不要用 SDL2::SDL2 目标 —— 其 interface 带 -mwindows，
#        会生成无控制台的 GUI 子系统程序（日志全看不见）
# 坑 3：SDL2_ROOT 必须在 find_package 之前 prepend
set(SDL2_ROOT "" CACHE PATH "Root of an SDL2 dev tree")
if(SDL2_ROOT)
    list(PREPEND CMAKE_PREFIX_PATH "${SDL2_ROOT}")
endif()
find_package(SDL2 QUIET)

target_link_directories(app PRIVATE "${SDL2_LIBDIR}")
target_link_libraries(app PRIVATE SDL2)          # 裸名，不用 SDL2::SDL2
```

**验证**：跑 `app --help` 应能在**终端**看到输出。若什么都没有，就是被 `-mwindows`
变成 GUI 子系统了。

## 四、其他高频配套坑

| 现象 | 根因 | 修法 |
|---|---|---|
| `'/*' within comment` 警告（生成的字体 `.c`） | 字体生成工具把命令行写进 banner 注释，路径含 `/*` | 后处理替换 banner 正文里的 `/*`（**保留** banner 开头的 `/*`，否则报 `expected identifier or '(' before '/'`） |
| `undefined reference to SDL_main` | 链接了 `SDL2main` 但 `main` 没改名 | 不链接 `SDL2main` |
| `undefined reference to __imp_WSAS*` | 手写 socket 服务缺 Winsock | `target_link_libraries(app PRIVATE ws2_32)`（仅 WIN32） |
| `undefined reference to libiconv_open` | 缺 iconv（GBK→UTF-8） | `find_package(Iconv)` + `Iconv::Iconv` |
| `%zu` 格式告警（MinGW） | MinGW 的 msvcrt `printf` 不支持 `%zu` | 全项目改 `%llu` / `%lld` |
| 枚举里 `::Level::ERROR` 变成 `::Level::0` | `<windows.h>` 把 `ERROR` / `WARN` 定义成宏 | 在 enum 声明前 `#undef ERROR` / `#undef WARN` |
| 显示端无控制台 | 被 `-mwindows` 变成 GUI 子系统 | 见第三节 |

## 五、移植切口（PC → MCU 时需要换的东西）

把平台相关代码**收拢到两个文件**，其余层（ui / 业务 / config）保持零平台依赖：

| 文件职责 | 内容 | MCU 替换为 |
|---|---|---|
| `platform/platform_time.*` | 本地时间、单调时钟、休眠 | HAL RTC + `HAL_GetTick()` |
| `platform/platform_http.*` | HTTP GET / POST JSON | 模组的 HTTP AT 指令 / lwIP httpc |
| `app/lvgl_port_*.cpp` | 窗口 / 输入 | 显示屏驱动 + 按键 / 触摸 |

**这样移植时只需改这 3 处**，ui 与业务代码原样复用。

## 六、最小验收清单

- [ ] `lv_init()` 在任何 `lv_*_drv_register()` 之前（**代码审查必查**）
- [ ] 主循环**没有** `lv_tick_inc()`（若已开 `LV_TICK_CUSTOM`）
- [ ] `LV_TICK_CUSTOM_INCLUDE` 指向的头是 C/C++ 双兼容
- [ ] SDL 窗口能弹出，分辨率与设计一致，无法拖拽缩放
- [ ] 终端里能看见应用日志（没被 `-mwindows` 吞掉）
- [ ] 关闭窗口后走**自己的**清理路径（不是 `exit(0)` 直跳）
- [ ] 连续运行 ≥10 s 不崩（覆盖 `lv_timer_handler` / `flush_cb` 路径）
