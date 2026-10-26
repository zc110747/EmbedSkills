# EmbedSkills

> 一位嵌入式固件工程师与 AI Agent 协作沉淀下来的 **Skill 库** —— 把「踩过的坑」写成 Agent 能直接调用的判据与配方。
>
> 当前 **41 个 Skill / 130 篇 references / 41 篇 SKILL.md（约 4885 行）/ 16285 行参考资料 / 11 个脚本**，全部 `agent_created: true`。
>
> ✅ 与本机 `~/.workbuddy/skills/` **已逐字节一致**（`bash sync_skills.sh --check` → `RESULT: IDENTICAL`）。
> 提交前建议再跑一次 `python lint_skills.py`（结构一致性，见「怎么用 · 4」）。

<p align="left">
  <img alt="skills" src="https://img.shields.io/badge/Skills-41-2b6cb0">
  <img alt="references" src="https://img.shields.io/badge/references-130-2f855a">
  <img alt="scripts" src="https://img.shields.io/badge/scripts-11-805ad5">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-718096">
  <img alt="platform" src="https://img.shields.io/badge/platform-MCU%20%7C%20SOC%20%7C%20%E4%B8%8A%E4%BD%8D%E6%9C%BA-c05621">
</p>

---

## 这是什么

**不是代码库，是「经验的可执行封装」。**

传统嵌入式知识沉淀的死法有两种：写进 README 没人看；写进笔记下次找不到。
本仓把经验写成 **Agent Skill** —— 每篇都带 `description` 触发词，Agent 在遇到
对应问题时**自动加载**，等于把「上次那个坑」变成「下次不再踩的能力」。

单条经验要进仓，必须满足三条**准入门槛**：

| 门槛 | 说明 | 反例 |
|---|---|---|
| **可判据** | 能写成「满足 X 则 Y」的规则，而非故事 | ❌「上次调了好久」 |
| **可复现** | 换项目、换板子仍成立，或明确标注适用芯片 | ❌「我这块板子上能跑」 |
| **有出处** | 引脚、寄存器、时钟、型号都核对过，未核对显式标注 | ❌「大概是这样」 |

> 隐含的第四条：**只写「反直觉」的部分**。`CMakeLists.txt` 怎么写不必进仓，
> 但「PowerShell 工具吞子进程输出，所以长构建必须走 Bash 后台」必须进仓。

---

## 仓库结构

```
EmbedSkills/
├── <skill-name>/               # 每个 Skill 一个顶层目录，命名带领域前缀
│   ├── SKILL.md                # 入口：name / description(≤120字符,机制+症状) / 何时用
│   ├── references/             # 细节：按需读取，不占常驻上下文
│   │   └── *.md
│   └── scripts/                # 确定性脚本（可选）：能脚本化的就别靠记忆
│       └── *.py
└── STM32_skills_能力表.md       # 速查索引
```

**三层加载模型** —— 这是整个设计里最省 token 的一环：

| 层级 | 内容 | 何时加载 | 成本 |
|---|---|---|---|
| **L1 · 常驻** | `name` + `description` | **每个会话自动注入** | 41 条 ≈ 3.4 K 字符 / **7.1 KB** |
| **L2 · 按需** | `SKILL.md` 正文（目标 2~4 KB） | 触发词命中时 | 单篇 ≈ 1/5 上下文 |
| **L3 · 精确** | `references/*.md` | 正文指向时才读那一篇 | 按需，通常 0 |

因此 `SKILL.md` 正文**只留知识点 / 判据 / 反模式 / 决策规则**，配方、完整配置、
报错对照表一律下沉到 `references/`。演进轨迹：2026-09 从 **39 个合并为 18 个**，常驻
description 总量 26 KB → 约 3 KB；2026-10-19 把 42 条全部压到 ≤150 字符；2026-10-26
**46 → 41 个**（合并 5 组同源 skill），description 从「功能清单堆砌」改写为
「机制 + 症状」，41 条实测 **3,400 字符 / 7.1 KB**，最长 117、平均 82，全部 ≤120 字符。

---

## 项目框架

```
                     ┌─────────────────────────────────────────┐
                     │   L0  方法论总入口                        │
                     │   mcu-ai-agent-workflow                  │
                     │   提示词四要素 · 分阶段验收 · 干预时机      │
                     └───────────────┬─────────────────────────┘
                                     │ 下游落地
        ┌────────────────────────────┼────────────────────────────┐
        ▼                            ▼                            ▼
┌───────────────┐          ┌─────────────────┐          ┌─────────────────┐
│  建  · 骨架    │          │  验  · 闭环      │          │  查  · 取证      │
├───────────────┤          ├─────────────────┤          ├─────────────────┤
│ stm32-build-  │          │ verification-   │          │ mcu-debug-      │
│ and-scaffold  │          │ and-acceptance  │          │ forensics       │
│               │          │                 │          │                 │
│ embedded-     │          │                 │          │ truth-source-   │
│ windows-      │          │ embedded-       │          │ and-model-      │
│ toolchain     │          │ config-portal   │          │ vendoring       │
└───────────────┘          └─────────────────┘          └─────────────────┘
        │                            │                            │
        └────────────────────────────┼────────────────────────────┘
                                     ▼
                     ┌─────────────────────────────────────────┐
                     │  平台 · 器件 · 领域层                     │
                     ├─────────────────────────────────────────┤
                     │ stm32-peripherals-and-memory            │
                     │ zephyr-stm32-porting                    │
                     │ esp32-platform-notes                    │
                     │ lvgl-mcu  · mcu-logging                 │
                     ├─────────────────────────────────────────┤
                     │ soc-video-and-edge-ai                   │
                     │ robotics-mechanism-and-sim              │
                     │ robotics-link-diagnostics               │
                     │ visual-verification                     │
                     ├─────────────────────────────────────────┤
                     │ schematic-pdf-netlist · mail-weekly-    │
                     │ digest                                  │
                     └─────────────────────────────────────────┘
```

---

## Skill 清单

### MCU / 嵌入式（11）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`mcu-ai-agent-workflow`](mcu-ai-agent-workflow/SKILL.md) | **L0 方法论**：AI 写嵌入式代码不难，难的是自我迭代闭环。提示词四要素、分阶段验收节奏、人工干预时机、认知误区 | 「用 AI 从零生成单片机工程」 |
| [`embedded-windows-toolchain`](embedded-windows-toolchain/SKILL.md) | Windows 主机的交叉编译（ARM GCC / ESP-IDF / Zephyr）与原生编译（MSVC + CMake/Ninja）环境搭建、构建执行、结果判据 | 「idf.py 构建」「PowerShell 输出被吞」 |
| [`stm32-build-and-scaffold`](stm32-build-and-scaffold/SKILL.md) | 工程骨架与双构建后端：目录分层、CMake+Ninja、启动文件、Keil MDK 移植、OpenOCD 烧录 | 「新建 STM32 工程」「链接报未定义 HAL 符号」 |
| [`stm32-peripherals-and-memory`](stm32-peripherals-and-memory/SKILL.md) | H7/F4 外设驱动与缓存/MPU 一致性判据：引脚映射、DCMI/SPI 屏/SD/QSPI/USB 实测坑、DMA 缓冲选址 | 「D-Cache 要不要关」「DMA 缓冲放哪」 |
| [`mcu-debug-forensics`](mcu-debug-forensics/SKILL.md) | 串口/板子不可用时的取证：SWD 读内存、HardFault 现场解码、中断链路诊断、自研 CMSIS-DAP 探针调优 | 「读内存验证变量」「探针下载慢」 |
| [`verification-and-acceptance`](verification-and-acceptance/SKILL.md) | **端到端验收 + 规模压测**（固件与上位机共用一套纪律）：断言前先等前置条件、读计数先记基线、负向对照证明脚本有牙齿、判据抽纯函数；固件侧双构零警告 + 真机烧录/串口/SWD，上位机侧 N 客户端与聚合恒等式 | 「验收固件」「写自测脚本」「压测 1000 客户端」「测试恒绿或 flaky」 |
| [`mcu-logging`](mcu-logging/SKILL.md) | 把裸 `printf` 换成编译期可控日志系统：单宏零成本关闭、栈缓冲避开重入、RTOS 懒互斥量 / 裸机 TX 中断环形缓冲 | 「串口打印卡死」「printf 重入」 |
| [`mcu-code-style`](mcu-code-style/SKILL.md) | **自研 C 代码规范 + 落地施工**：文件级静态变量合并为结构体（同一件事才合并）、按暴露数量选接口粒度、只读返回 `const` 指针、注释摘要化、第三方代码不动只上报；附 clang-format 配置、GBK 编码保护、目录大小写改名、static 合并、MDK+GCC 双构验证与提交拆分 | 「静态变量怎么组织」「给某工程应用 code style」「按新规范更新老项目」 |
| [`mcu-cpp-development`](mcu-cpp-development/SKILL.md) | 用 C++ 写单片机的代码方法与格式：C/C++ 混合链接与 `extern "C"`、模板 + `constexpr` 零成本外设封装、`new/delete` 重载、Makefile 双编译 | 「C++ 开发单片机」「混合编译」「undefined reference 函数重载」 |
| [`embedded-config-portal`](embedded-config-portal/SKILL.md) | 运行期配置门户：SoftAP + 内嵌网页、唯一真值源、读写串行化、WebSocket 快照推送、无硬件前端断言 | 「网页显示的状态不对」 |
| [`avr-flash-ram`](avr-flash-ram/SKILL.md) | AVR(avr-gcc/avr-libc) RAM 溢出：字符串字面量默认进 .data 挤爆栈，致固件空载正常、收命令即复位。avr-size/nm/objdump 定位、PSTR/PROGMEM 正解、%S 与 %s 区别 | 「AVR 收命令复位」「.data 异常大」 |

### 显示 / GUI（1）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`lvgl-mcu`](lvgl-mcu/SKILL.md) | **LVGL v8/v9 渲染与移植**：四类静默失败（有框无字 / 豆腐块 / 曲线塌陷 / 内容永远是旧的）、子集字库与 SD 卡 TTF 流式栅格化引擎、v9 破坏性变化（`LV_TICK_CUSTOM` 删除致首屏冻结、`lv_color_hex` 改 RGB888、`lv_screen_load`）、framebuffer 移植、启动动作条与多屏交接、短命帧 SWD 取证 | 「字库缺字」「豆腐块」「首屏冻结」「复位彩条」「v8 升 v9」 |

### 平台移植（3）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`zephyr-stm32-porting`](zephyr-stm32-porting/SKILL.md) | 裸机外设搬进 Zephyr 的差异点：west 工作区、设备树 overlay、时钟树、ST7789 点亮、GBK 点阵字库、Shell | 「ST7789 全黑」 |
| [`esp32-platform-notes`](esp32-platform-notes/SKILL.md) | Arduino CLI 与 ESP-IDF 两条构建链：构建范式、板级硬件、Cortex-Debug、组件链接陷阱 | 「openocd 报 Arg list too long」 |
| [`ra8d1-fsp-platform-notes`](ra8d1-fsp-platform-notes/SKILL.md) | Renesas RA8D1（R7FA8D1BH / Cortex-M85 + FSP）平台经验：内存映射、GLCDC/RGB 与 MIPI DSI、xSPI/OSPI 串行 Flash、PFS 引脚复用、SWD 取证；烧录与 VSCode 源码级调试走 pyOCD 注入（见 `pyocd-flm-inject-debug` 的 RA8D1 实例） | 「RA8D1 显屏不出图」「OSPI CS 通道」「RA8D1 无法调试」 |

### SOC / 视频 / 边端 AI（1）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`soc-video-and-edge-ai`](soc-video-and-edge-ai/SKILL.md) | 三条链路：设备侧 RTSP 推流 Agent、流媒体服务端（MediaMTX + WebRTC/HLS）、零依赖 YOLO/ByteTrack 旁路 | 「HLS 黑屏」「端侧 AI 不影响视频流」 |

### 上位机应用层 / C++20 协程（2）

**非固件**方向：宿主侧 C++20 运行时、单线程网络服务、大规模客户端验收。前缀 `app-`。
压测与规模验收统一走 `verification-and-acceptance`。

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`app-cpp20-coroutine-runtime`](app-cpp20-coroutine-runtime/SKILL.md) | 单线程协作式协程运行时的**静默失败**：五条不变量、generation 计数唤醒协议（替代锁、根治双重 resume）、帧归属与进程级泄漏断言、取消是状态不是信号、header-only 的 inline/ODR 漏网、定时器堆惰性删除、通道背压 | 「C++20 协程」「co_await 卡住」「双重 resume」「协程帧泄漏」「header-only 重复符号」 |
| [`app-select-relay-server`](app-select-relay-server/SKILL.md) | 单线程 `select()` 服务的规模上限与可移植性：Windows `FD_SETSIZE=64` 令 `FD_SET` **静默截断**（能连上、被计入在线、数据被无声丢弃）、`listen` 必须非阻塞、`backlog` 要覆盖 accept 节奏、错误文本本地化破坏纯 ASCII 契约 | 「客户端一多就丢数据」「连接被拒」「accept 挂死」 |

### 上位机桌面应用（.NET / C#）（2）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`winforms-desktop-app`](winforms-desktop-app/SKILL.md) | C#/.NET WinForms 桌面应用：自绘圆角控件的 DPI 与裁剪、NAudio 2.x→3.x 破坏性改名、`DeviceCount==0` 是合法环境、**WFO1000 与 `[DefaultValue]`**、同一个 exe 兼作 CLI（`AttachConsole` 顺序陷阱）、xUnit 2.x 没有 `Assert.Skip` | 「WinForms 自绘控件」「NAudio 播放」「GUI 当 CLI 用」 |
| [`piper-offline-tts`](piper-offline-tts/SKILL.md) | Piper 本地离线 TTS 集成：CLI 契约（正文走 **stdin**、`-f` 出 WAV）、长文本实测能力、喂 TTS 前的文本准备（章节抽取 / 仅接受 UTF-8 / 非目标语言闸门）、模型哈希与许可核对、WAV 原子落地 | 「本地 TTS」「Markdown 转语音」「模型哈希核对」 |

### 复刻（逆向 → 替身 → 复现）（4）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`replica-recon`](replica-recon/SKILL.md) | 复刻第一步**逆向取证**：确认原件身份与版本、PE/容器静态解析、资源与字符串挖掘、行为观察，每条结论按**证据强度**分级 | 「复刻某工具先摸清它怎么做的」 |
| [`replica-memory-engine`](replica-memory-engine/SKILL.md) | 从外部读写目标进程内存的引擎：符号解析、AOB 签名扫描（通配展开 / 越界钳制 / 全量校验）、多级指针链、位域读写、代码洞与跳板 hook、x64 指令长度解码 | 「AOB 一条都命中不了」「指针链走到一半变空」 |
| [`replica-mock-harness`](replica-mock-harness/SKILL.md) | **没有目标程序时的验收**：自研替身进程验证「读地址→指针链→写值→回读」整条接线，PASS/FAIL/SKIP 三分类把「环境缺位点」与「接线坏了」分开，SKIP 清单即真机补验 TODO | 「替身进程怎么造」「验收脚本总报 FAIL」 |
| [`replica-ui-fidelity`](replica-ui-fidelity/SKILL.md) | 从参考截图**逐像素反推**复刻界面：布局度量标定、DPI 缩放、字号实测标定、色值采样、自绘控件与真实子窗口遮挡、像素级复验 | 「照着截图把界面做出来」「DPI 缩放后全错位」 |

### 机器人 / 多物理场（5）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`truth-source-and-model-vendoring`](truth-source-and-model-vendoring/SKILL.md) | 同一份真值在多处实现、或多份官方模型之间的**静默漂移**：冻结基线、语义核心哈希、多实现互证 | 「URDF 与 MJCF 对不上」「Sim2Sim 一致性」 |
| [`robotics-mechanism-and-sim`](robotics-mechanism-and-sim/SKILL.md) | 机构几何真值取证（照片/CAD 反解）与 MuJoCo 对等实现、容差登记、判据验证 | 「仿真没复现真机行为」 |
| [`robotics-link-diagnostics`](robotics-link-diagnostics/SKILL.md) | 上位机 ↔ 机械臂链路：串口/字节层、TCP/WS 关节级链路「谁引起谁跟随」、`origin` 语义、命令门控 | 「两条链路口径不一致」 |
| [`arm-photo-texturing`](arm-photo-texturing/SKILL.md) | 实拍照片给刚体/机械臂模型贴真实纹理（Level3→4 视觉增强，非几何重建）：大面法向判定、拍摄协议、四角定位、透视校正、three.js 按面材质与 envMap | 「照片贴图」「透视校正」「数字孪生视觉增强」 |
| [`motor-telemetry-alias-proof`](motor-telemetry-alias-proof/SKILL.md) | 读数上蹿下跳到底是欠采样旋转波形、真噪声还是饱和钳位：按相位分箱看离散度塌缩，配物理律/链路闭合/混叠比三判据 | 「PWM/相电流跳动」「波形像噪声」「数据在抖是 bug 还是采样」 |

### 前端 / Windows GUI 取证（2）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`visual-verification`](visual-verification/SKILL.md) | **看不到界面时怎么验**（Web + Windows GUI 共用一套方法）：Web 侧沙箱封掉 Chromium 时用 esbuild 打包客户端模块打活服务、`react-dom/server` 渲染每个组件、WebGL 首帧逐帧取证；Windows 侧 ctypes+BitBlt 抓客户区、DPI 感知点击、纯 Python PNG 裁剪放大、单调用编排 | 「页面显示 undefined 却不报错」「GUI 截图」「自动化验收」「点击没反应」「DPI 缩放」 |
| [`wpf-realtime-sim`](wpf-realtime-sim/SKILL.md) | WPF+MVVM 实时仿真/遥测看板：解耦后台步进线程、30FPS 刷新、自更新 Canvas 趋势图、暗色主题(含 ComboBox 模板)、离屏 PNG 验证 | 「WPF 实时仿真」「无图表库趋势图」「暗色 ComboBox」 |

### 静态站 / WebView 套壳（4）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`web-static-site-pipeline`](web-static-site-pipeline/SKILL.md) | 只用 Python 标准库把 Markdown 内容源构建成静态站：可复现构建（逐字节比对）、校验断言按能力分叉、watch 全量重建、CSS/JS 内容指纹与 Pages `max-age=600` 缓存坑 | 「静态站加文章」「构建没产出」「校验假 FAIL」「改了样式手机不生效」 |
| [`web-local-progress-store`](web-local-progress-store/SKILL.md) | 无后端的本地进度：localStorage 版本化、导出/导入 JSON 逐字节同构、合并 vs 覆盖与二次确认、坏存档备份、跨端镜像成同一个文件 | 「离线存进度」「导出导入」「覆盖丢记录」「两端数据对不上」 |
| [`app-webview-shell`](app-webview-shell/SKILL.md) | 网页套壳（WinForms WebView2 / 系统 Android WebView）：三态启动、导航看门狗、离线错误菜单、进度桥接注入、离屏抓图验收 | 「网页套壳」「启动白屏」「离线要提示」「抓图空白」 |
| [`android-apk-no-gradle`](android-apk-no-gradle/SKILL.md) | 不装 Gradle 也能量产 APK：aapt2→javac→d8→zipalign→apksigner 全链路、固定签名可覆盖升级、图标白边与真机安装坑 | 「机器没有 Gradle」「apk 装不上」「桌面图标白边」「INSTALL_FAILED_ABORTED」 |

### 工具类（6）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`schematic-pdf-netlist`](schematic-pdf-netlist/SKILL.md) | 从 EDA 导出的原理图 PDF 反解网表与引脚映射，写成含电源树与 NC 引脚的硬件规格文档 | 「解析原理图 PDF」 |
| [`pyocd-flm-inject-debug`](pyocd-flm-inject-debug/SKILL.md) | 芯片无内建 pyOCD target、或 pack target 在 CMSIS-DAP 上初始化失败时：用 `pyocd_user.py` 的 `will_init_target` 钩子注入 memory map + 官方 FLM 闪存算法，打通烧录与 VSCode F5；含 TrustZone 芯片（RA8D1：4 个 FLM、SCons 构建、headless 自测脚本）实例 | 「pyocd 烧不了」「cortex-debug 连不上」「RA8D1 无法调试」 |
| [`mail-weekly-digest`](mail-weekly-digest/SKILL.md) | 指定周期的邮箱汇总周报，统计收发/未读/附件并按来源归类，产出深色极简 HTML | 「邮箱周报」 |
| [`deterministic-clock-testing`](deterministic-clock-testing/SKILL.md) | 把时间抽象成可注入 TimerLike+FakeTimer，让依赖延迟/节流/超时/重试的代码可确定性测试（无真实 sleep）：最小接口、FakeTimer 四要点、四类断言 | 「定时器测试」「节流测试」「flaky 测试」「假时钟」 |
| [`git-silent-source-loss`](git-silent-source-loss/SKILL.md) | 源文件凭空消失/换机编译不过：.gitignore 误匹配源文件 + git add 静默跳过。三步定位、修复(!例外+注释)、类案清单 | 「文件不见了」「git add 不生效」「clone 缺文件」 |
| [`win-batch-sandbox-probe`](win-batch-sandbox-probe/SKILL.md) | Windows 批处理坑与沙箱等效验证：块内 echo 裸括号提前闭合、Python subprocess 真跑 .bat、进程树回收、shell 追加重写覆盖、file-history 救援 | 「bat 报 此时不应有 or」「沙箱跑 bat」「追加没生效」 |

---

## 跨 Skill 的复用链

Skill 之间**显式互相引用**，常用组合：

| 场景 | 调用链 |
|---|---|
| **从零做一个 MCU 工程** | `mcu-ai-agent-workflow` → `stm32-build-and-scaffold` → `embedded-windows-toolchain` → `verification-and-acceptance` |
| **板子「像死了」** | `mcu-debug-forensics`（先定性） → `stm32-peripherals-and-memory`（查缓存/MPU） → `mcu-logging`（补可观测性） |
| **屏上显示不对** | `lvgl-mcu` → `stm32-peripherals-and-memory`（屏/总线） → `zephyr-stm32-porting`（若走 RTOS） |
| **给设备加网页配置** | `embedded-config-portal` → `visual-verification`（无硬件验证前端） → `verification-and-acceptance` |
| **改机构参数前** | `robotics-mechanism-and-sim`（量真值） → `truth-source-and-model-vendoring`（防漂移） → `robotics-link-diagnostics`（验链路） |
| **做一个上位机网络服务** | `app-cpp20-coroutine-runtime`（事件循环若是协程调度器） → `app-select-relay-server`（规模上限与运维契约） → `verification-and-acceptance`（压测验收） |
| **服务「客户端一多就丢数据」** | `app-select-relay-server`（`FD_SET` 截断 / `backlog`） → `verification-and-acceptance`（复现 + 负向对照） |
| **要复刻一个外部工具** | `replica-recon`（先摸清它怎么做的） → `replica-memory-engine`（读写引擎） → `replica-mock-harness`（没原件就造替身验收） → `replica-ui-fidelity`（界面 1:1） |
| **把一个静态站做成多端 App** | `web-static-site-pipeline`（站本体与缓存） → `web-local-progress-store`（本地状态与导出契约） → `app-webview-shell`（桌面/手机外壳） → `android-apk-no-gradle`（出安装包） |

---

## 适用人群

### ✅ 强烈适合

- **嵌入式固件工程师** —— STM32 / ESP32 / Zephyr 方向。可以直接抄判据，省掉重复踩坑。
- **正在用 AI Agent 写嵌入式代码的人** —— 尤其 `mcu-ai-agent-workflow`：它会告诉你
  AI 生成的代码不是瓶颈，瓶颈在「交叉编译 + 烧录 + 仿真 + 真机验证」的自我迭代闭环。
- **接手别人板子 / 二手开发板的人** —— 引脚、外设、时钟、型号的**核对方法**比结论更有价值。
- **把「经验资产化」当刚需的团队** —— 这里的组织方式（常驻/按需/精确三层 + 准入门槛）
  可以直接搬去建自己的内部 Skill 库。

### ⚠️ 部分适合

- **纯 Linux 应用开发者** —— 只有 `visual-verification`、`truth-source-and-model-vendoring`
  两篇与硬件无关，其余价值有限。
- **用 HAL 库照着例程走的人** —— 本仓刻意**不写**「怎么调 HAL 函数」，只写反直觉部分，
  你会觉得很多基础内容「没写」。
- **想要现成可编译工程的人** —— 这里**没有一行产品代码**，全是判据、配方与脚本。

### ❌ 不适合

- 寻找开箱即用的固件框架 / BSP 库的人（本仓不含可编译工程）。
- 需要官方支持与 SLA 的商业场景（这是个人经验沉淀，按现状提供）。
- 需要严格版本承诺的场景 —— 芯片型号、工具链版本都在文中标注，但**换板必须重新核对**。

---

## 怎么用

### 1. 作为 Agent Skill 安装（推荐）

把任一 Skill 目录复制到 Agent 的 skill 目录：

```bash
# 单个安装
cp -r stm32-build-and-scaffold ~/.workbuddy/skills/

# 全量安装
for d in */; do
  [ -f "$d/SKILL.md" ] && cp -r "$d" ~/.workbuddy/skills/
done
```

安装后**新开会话**生效 —— `name` + `description` 会被自动注入，
命中触发词时 Agent 主动加载对应 `SKILL.md`，无需手动 @。

> 本仓与作者本地 `~/.workbuddy/skills/` 保持逐字节一致，`references/` 与 `scripts/` 一并携带，
> 单独复制 `SKILL.md` 会导致正文里的「详见 references/...」指向空文件。

### 2. 当文档直接读

不想装 Skill 也能用：从 [`STM32_skills_能力表.md`](STM32_skills_能力表.md) 速查，
或直接进目录读 `SKILL.md` → 需要细节再进 `references/`。

### 3. 当作模板建自己的库

照抄这套约定即可：

```
SKILL.md 正文 ≤ 6 KB（目标 2~4 KB）
description ≤ 120 字符（硬上限 150），写「机制 + 症状」，第三人称
细节一律下沉 references/，正文只留判据
能脚本化的写进 scripts/，不靠记忆
```

### 4. 与系统 skills 保持同步（作者用）

本仓是作者本地 `~/.workbuddy/skills/` 的**唯一版本化镜像**（一个仓覆盖所有工程；
各工程**直接使用全局 skills**，不再在工程内维护 `.workbuddy/skills/` 镜像）。

```bash
cd EmbedSkills
bash sync_skills.sh              # 全局 -> EmbedSkills（默认，刷新镜像）
bash sync_skills.sh --check      # 只报漂移（0=一致, 1=有漂移）
bash sync_skills.sh --list       # 打印纳管清单
bash sync_skills.sh --prune      # 清理镜像侧冗余文件（全局已删的残留）
bash sync_skills.sh --restore    # EmbedSkills -> 全局（换机 / 灾后恢复）
python lint_skills.py            # 结构一致性校验（frontmatter / ≤150 / 引用链接）
```

纳管范围**两侧都自动发现再取并集**（全局 skills 下每个顶层 skill 目录 + 顶层 `.md`），仅排除
`README.md` / `.git` / `.workbuddy` / `sync_skills.sh` / `lint_skills.py` —— 刻意**不做写死白名单**：
旧版把 18 个名字硬编码，skill 改名/合并后清单全部失效、静默漏同步（2026-09-30 实测 18 个名字里 16 个已不存在）。

> ⚠️ 只扫全局一侧会让 `--restore` 补不上「全局缺、镜像有」的目录（2026-10-19 实测：全局被回退
> 少了 15 个 skill，`--restore` 后仍报漂移）。现已改为两侧并集，`--check` 会直接告诉你跑哪条命令：
> `[仅全局存在→需 sync]` / `[仅镜像存在→需 restore]`。

> ⚠️ 沙箱/受限 shell 内**脚本批量删除**会被 `SIGTERM` 中断（stdout 也一起丢）→
> `--prune` 请在真实终端执行，或让 Agent 逐条 `rm`。

---

## 规划

### 已完成

- [x] **2026-08** 仓建立，沉淀第一批嵌入式 Skill
- [x] **2026-09-21** 大整理：**39 → 18 个 Skill**，description 总量 **26 KB → 3 KB**
      - 合并同域碎片（如 5 个 STM32 外设 Skill 并为一个 + 7 篇 references）
      - 全部补齐 `agent_created: true` frontmatter
      - 退役副本保留于 `~/.workbuddy/skills.retired-2026-09-21/`（36 个，**零删除**）
      - 完整备份 `~/.workbuddy/skills.bak-2026-09-21/`
- [x] **2026-09-21** 建立本仓 ↔ 系统 skill 目录的同步机制
- [x] **2026-09-29** 与系统目录再同步并精简：**18 → 19 个 Skill / 68 → 78 篇 references**
      - 补齐系统侧新增：`mcu-comment-style`（整 skill，2026-09-30 改名为 `mcu-code-style`）、`mail-weekly-digest`（恢复误删的 3 文件）
      - 补齐 11 篇新 references：ESP32 的 GT911/RGB 面板/SPI-SD/WiFi-STA、SOC 的采集取证/多轴耦合/录制器/前端验收、控制侧累积量、控制台批处理陷阱
      - 合并系统丰富版 11 项（`verify-script-patterns.md` 208 → 499 行、`soc-video-and-edge-ai/SKILL.md` 51 → 109 行等）
      - 去重：3 组跨 skill 重复命令（ffplay 低延迟参数组、`python -m west build`、`idf.py` 包装器）收敛到唯一出处 + 指针
      - 修复 4 处 SKILL.md 索引缺失（`hls-latency-tuning.md`、`h7-flash-bootloader.md`、`lan8720a-rmii.md`、`uart-physical-bridge.md`）
- [x] **2026-09-30** 同步系统侧 4 项新增 + 增设 C 代码规范规则 → **20 个 Skill / 79 篇 references**
      - 同步新 skill `mcu-cpp-development`（C++ 写单片机：混合链接、模板零成本封装、`new/delete` 重载）
      - 同步 `stm32-build-and-scaffold`：新增 armlink 分散加载三条硬语法与 TinyUSB 弱钩子（`keil-port.md` 240 → 399 行）
      - `mcu-comment-style` **改名并扩写为 `mcu-code-style`**：新增「文件级静态变量合并为结构体」「按暴露数量选接口粒度」「第三方代码不动只上报」三节
      - 全仓交叉引用同步改名（`mcu-cpp-development`、README、能力表）
- [x] **2026-09-30** `sync_skills.sh` **入仓并改架构**（`EmbedSkills/sync_skills.sh`）
      - 同步脚本从工程侧（`MCU-Agent/support_tools/`）迁到**本仓**，方向改为
        `全局 ~/.workbuddy/skills/` ⇄ **EmbedSkills**；**取消工程级 `.workbuddy/skills/` 镜像**，
        各工程直接使用全局 skills（一个仓覆盖多工程）。
      - 纳管清单由**写死白名单改为目录自动发现**，根治"skill 改名/合并后静默漏同步"。
      - 新增孤儿检测（`[仅镜像存在]`）、`--check`/`--list`/`--prune`/`--restore` 全通。
- [x] **2026-10-12** 新增**上位机应用层**方向（前缀 `app-`）：3 篇新 Skill，并补齐此前只在全局
      存在的 4 篇（`lvgl9-mcu-porting`、`ra8d1-fsp-platform-notes`、`ra8d1-vscode-pyocd-debug`、
      `pyocd-flm-inject-debug`）→ **29 → 36 个 Skill / 87 → 98 篇 references / 10 → 12 个脚本**
      - 来源工程：一个 C++20 协程库 + 基于它的 TCP 中继服务 + 三层 Python 验收链
      - `app-cpp20-coroutine-runtime`：五条不变量、generation 计数替代锁、帧归属与进程级泄漏断言、
        header-only 的 inline/ODR 漏网、定时器堆惰性删除、通道背压
      - `app-select-relay-server`：Windows `FD_SETSIZE=64` 的 `FD_SET` **静默截断**（含"用 0 号
        客户端复现会得出相反结论"的诊断陷阱）、`listen` 非阻塞、`backlog` 与 accept 节奏、
        错误文本本地化破坏纯 ASCII 契约、零依赖配置子集
      - `app-host-load-acceptance`：三条纪律（先等前置条件 / 基线 / 断言分层）、聚合恒等式做无损
        证明、**负向对照证明脚本有牙齿**（实测坏二进制 11/18 FAIL，签名与手工复现一致）
      - 附 2 个已验证脚本：`probe_fdset.c`（`FD_SETSIZE=64 → stored 64/128`；
        `-DFD_SETSIZE=8192 → 128/128`）、`net_load_harness.py`（stdlib-only，自带 loopback 自检 5/5）
      - 3 篇 description 均 ≤150 字符；与 `embedded-verification-acceptance`、
        `win-batch-sandbox-probe` 交叉引用，不重复既有内容
- [x] **2026-10-16** 新增**上位机桌面应用**方向：2 篇新 Skill → 本仓 **40 → 42 个 Skill / 110 → 116 篇 references**
      - 来源工程：一个 C# / .NET 10 WinForms 本地离线英语语音工具（Piper TTS → WAV → 内建播放器）
      - `winforms-desktop-app`：NAudio 2.x→3.x 的破坏性改名（`WaveOutEvent`→`WaveOut`、
        `DesiredLatency`→`BufferMilliseconds`、`GetPositionTimeSpan` 变 `NAudio.Utils` 扩展方法）、
        自绘圆角卡片的**角缝补色**与 `SetClip(GraphicsPath)`、`TextRenderer` vs `DrawString`、
        DPI 现算缩放、**WFO1000 与 `[DefaultValue]`**、`DeviceCount == 0` 是合法环境、
        xUnit 2.x **没有** `Assert.Skip` 只能靠条件 `FactAttribute` 子类
      - `piper-offline-tts`：CLI 契约（正文走 **stdin**、`-f` 出 WAV、`espeak-ng-data` 随 exe 自动发现）、
        **实测长文本无实际上限**（7,499 字符一次 stdin → 500.6 s 单文件 / RTF ≈ 0.07，
        68 字符 → 4.46 s / 22,050 Hz mono 16-bit）、运行时 MIT 与模型（LJ Speech 公有领域）的
        来源/版本/哈希核对口径、WAV 临时文件 + `File.Move` 原子落地
      - 2 篇 description 分别为 **132 / 127** 字符，均 ≤150；新增「上位机桌面应用（.NET / C#）」分类
- [x] **2026-10-16（补）** 同一来源工程追加了**命令行模式**，把 3 组判据回填到已有的 2 篇 Skill
      （**42 个 Skill / 116 → 118 篇 references**）
      - `winforms-desktop-app/references/gui-exe-as-cli.md`（新增）：
        子系统取舍（`WinExe` vs `Exe`）、**`AttachConsole` 必须在读 `Console.IsOutputRedirected` 之前调用**
        （顺序反了 ⇒ 真实 cmd 窗口静默无输出，而管道环境测试**全绿**，这是最阴的一种失败形态）、
        "抓不到输出≠没输出"的**探针取证法**（attach/redirected/streamNull 打一行日志）、
        批处理包装器解决"提示符不等待"、分级退出码、`SafeTextWriter` 让"打印失败"不升级成"业务失败"
      - `piper-offline-tts/references/text-prep-for-tts.md`（新增）：
        只抽取目标章节（到同级/更高级标题截止、代码块里的 `#` 不算标题）、
        **剥语法但不丢文字**（表格按行成段、链接保留可见文字丢 URL、实体还原）、
        **仅接受 UTF-8 的四重判据**（BOM → NUL 占比 → 严格解码 → 控制字符兜底）、
        非目标语言**在合成前**中止并报脚本名与码位、输出路径规则必须抽成纯函数单测
      - 第一篇 SKILL.md 的 description 补充"同一个 exe 兼作命令行"，两篇核心知识点表各加 1~2 行

- [x] **2026-10-19** 同步 + 瘦身 + 工具化（**42 个 Skill / 118 篇 references / 12 个脚本**）
      - **解掉镜像漂移**：全局 `~/.workbuddy/skills/` 被回退到旧快照（比镜像少 15 个 skill 目录），
        `--restore` + 增量补齐后 `--check` 得 `RESULT: IDENTICAL`（42 skill + 1 文件）。
        修复前整份备份到 `~/.workbuddy/skills.bak-20261019/`。
      - **修掉 `sync_skills.sh` 的设计缺口**：纳管清单原先只扫全局 ⇒ `--restore` 永远补不上
        「全局缺、镜像有」的目录（本次只能手动 `cp` 15 个目录才收敛）。现改为**两侧都扫再取并集**，
        一次即可收敛；`--check` 输出改为自解释的 `[仅全局存在→需 sync]` / `[仅镜像存在→需 restore]`，
        并删掉与之重复的「仅镜像存在」扫描段（少一段代码、少一种口径）。
      - **11 篇 description 全部压到 ≤150 字符**（441/276/224/216/204/194/179/178/162/161/156 → 全部合规），
        42 条常驻 **6,328 → 5,427 字符（11.4 KB，省 14%）**；压缩时优先砍中文触发词、保留英文实体
        （`pyocd` / `cortex-debug` / `r_ospi_b` / `AOB` 等权重更高）。
      - 补齐 3 篇缺失的 `agent_created: true`（`lvgl9-mcu-porting`、`mcu-code-style-apply`、
        `ra8d1-vscode-pyocd-debug`）——frontmatter 不全时宿主可能不加载该 skill。
      - 新增仓根 **`lint_skills.py`**（零依赖、可直接进 CI）：校验 frontmatter 闭合、`name` == 目录名、
        `description ≤150`、`agent_created: true`、正文首行 H1、`references/` 链接有效性
        （支持 `其他skill/references/x.md` 跨引用，避免误报）。首次运行即抓出上述 5 个真实缺陷。
      - 能力表补登漏列的 11 个 skill（31 → **42**），README 清单补 6 个（36 → **42**）：
        新增「上位机桌面应用（.NET/C#）」与「复刻（逆向→替身→复现）」两个分组。

- [x] **2026-10-19** 新增「静态站 / WebView 套壳」方向：4 篇（**42 → 46 个 Skill / 118 → 123 篇 references**）
      - `web-static-site-pipeline`：内容源→HTML 的构建/校验/监听约定，含**可复现判据**（重构建到临时目录
        逐字节比对）、校验断言按**页面能力分叉**（否则空集合 → 假 FAIL）、资产内容指纹与
        Pages `max-age=600` 的组合坑（"改了没生效"的**三步定位**：部署物 → 缓存 → 代码）。
      - `web-local-progress-store`：把「导出 JSON」当**对外契约**（缩进 / 键序 / 行尾 / 结尾换行），
        导入两段式（预览 → 合并或覆盖），覆盖必须二次确认；坏存档备份后重置；纯逻辑抽离到
        `globalThis` 才能在 Node 里真跑；跨端镜像时 .NET 的 CRLF 与网页的 LF 不一致会破坏比对。
      - `app-webview-shell`：三态启动（启动页 → 探网 → **导航成功才**显示网页）是整篇的主轴，
        附两端差异（Windows 注入可早于导航；系统 WebView 只能在 `onPageFinished` 注入，
        要"探存储 → 写种子 → reload 一次"并加一次性守卫），以及 Android 两个必崩点
        （`GONE` vs `INVISIBLE`、`InsetsController` 取用时机）。
      - `android-apk-no-gradle`：六步链路与各步真实参数（`--v4-signing-enabled false` 免出 `.idsig`、
        `zipalign` 必须在签名前、`-I` 与 `javac -classpath` 同一份 `android.jar`），
        外加真机安装三类坑（息屏拒绝确认、签名不一致、Git Bash 路径转换）。
      - 新增 5 篇 references（全库参考资料 15139 → **15494 行**），全部 `agent_created: true`、description ≤150 字符。

- [x] **2026-10-26** 适配新模型 + 去重精简（**46 → 41 个 Skill / 123 → 130 篇 references**）
      - **动机**：46 条 description 全部顶在 150 上限（149/149/147…），常驻 5,899 字符已从
        「触发词」退化成「功能清单」——满额堆砌让新一代模型更难区分相邻 skill。
        实测正文两两 6-gram Jaccard 相似度最高仅 5.2%，说明**不是文本重复，而是职责重叠**。
      - **合并 5 组同源 skill**（被吞并篇的独有内容一律下沉 `references/`，零删除）：
        - `pyocd-flm-inject-debug` ← `ra8d1-vscode-pyocd-debug`：同一注入机制，后者是 TrustZone
          芯片实例（正文相似度 5.2%，全库最高）→ 实例参数移入 `references/ra8d1-instance.md`
        - `mcu-code-style` ← `mcu-code-style-apply`：后者正文首行即自述「规范本体见另一篇」，
          两篇必须同时加载才可用 → `references/apply-to-legacy-project.md`
        - `lvgl-mcu`（新）← `lvgl-font-and-render` + `lvgl9-mcu-porting`：同域，且后者 §4/§6
          与验收、调试取证两篇重复 → 新增 `references/v9-migration.md`、
          `references/boot-splash-and-swd.md`，原 5 篇 references 与 5 个脚本全部继承
        - `verification-and-acceptance`（新）← `embedded-verification-acceptance` +
          `app-host-load-acceptance`：同一套纪律（断言前等前置 / 读计数先记基线 / 负向对照 /
          判据抽纯函数），只是观测手段不同 → 两份完整原文保留为 `references/*-playbook.md`
        - `visual-verification`（新）← `web-headless-verification` + `win-gui-screenshot-verify`：
          同一个问题「看不到界面时怎么验」→ Windows 完整配方移入 `references/win-gui-capture.md`
      - **description 全部重写**为「机制 + 症状」两段式，砍掉「适用于…等请求」的同义堆砌：
        41 条 **5,899 → 3,400 字符（7.1 KB，省 42%）**，最长 117、平均 82，全部 ≤120（留余量）。
      - 交叉引用同步：12 个文件里的旧 skill 名改到新名（含 `references/` 内的跨篇指针、
        `apply-to-legacy-project.md` 里过期的 `support_tools` 同步说明）。
      - 旧目录整体退役到 `~/.workbuddy/skills.retired-2026-10-26/`（8 个），合并前整份
        备份到 `~/.workbuddy/skills.bak-20261026/`。

### 进行中 / 计划

- [x] ~~**解掉镜像漂移**~~ —— 2026-10-19 已完成，现为 `RESULT: IDENTICAL`。
- [x] ~~**收敛超长 description**~~ —— 2026-10-19 已完成，42 条全部 ≤150 字符（共 5,427 字符）。
- [x] ~~**description 适配新模型**~~ —— 2026-10-26 已完成，41 条 ≤120 字符（共 3,400 字符），
      结构改为「机制 + 症状」。
- [x] ~~**去重合并**~~ —— 2026-10-26 已完成，46 → 41（5 组同源 skill 合并，内容零删除）。
- [ ] **安装脚本** —— 让「全量安装」从手抄 `for` 循环变成 `install.sh` / `install.bat`（Windows 侧纯 ASCII、pause-on-error）。
- [ ] **CI 一致性校验** —— `lint_skills.py` 已覆盖规则；还差把它挂到 pre-commit / GitHub Actions（`.github/` 目前为空）。
- [ ] **正文偏大的 20 篇待分流** —— 按 UTF-8 字节数 >6 KB，最大 `ra8d1-fsp-platform-notes`(19.3 KB) /
      `win-batch-sandbox-probe`(17.4 KB) / `arm-photo-texturing`(17.1 KB) / `mcu-code-style`(16.1 KB)。
      内容密度高、无明显水分，属于「L2 按需加载」而非常驻成本，暂不动；若要瘦身，做法是
      **下沉到同 skill 的 `references/`（不删除内容）**，而不是砍判据。
- [ ] **领域扩展** —— 边缘 AI 部署（ONNX / CMSIS-NN 量化链路）、嵌入式 Linux SOC（RK3568 摄像头/RTSP）方向仍偏薄。

---

## 维护约定

- **改动的落点别搞反**：全局 `~/.workbuddy/skills/` 是**权威副本**。要改 skill 就**先改全局**，
  再 `bash sync_skills.sh` 刷镜像；反向操作（改镜像后跑 `sync`）会被全局旧副本**静默覆盖**，
  而 `sync` 还会打印 `RESULT: OK`（因为两边"一致"了，只是都变成了旧版）。2026-10-19 已踩过一次。
  仓独有文件（`README.md`、能力表）另说：README 不纳管，能力表改完要 `cp` 回全局。
- **目录布局**：`<skill>/SKILL.md` + `references/*.md`（细节）、`scripts/`（确定性脚本）。
- **frontmatter 五行**：`---` / `name` / `description`（≤120 字符，硬上限 150；「机制 + 症状」结构、第三人称）/ `agent_created: true` / `---`。
- **提交前两条命令**：`bash sync_skills.sh --check` 要 `RESULT: IDENTICAL`，`python lint_skills.py` 要 `RESULT: OK`。
- **零删除原则**：整理时旧版本整体退役到带日期的备份目录，可原样搬回。
- **不写敏感信息**：本仓不含任何 token、凭据、密钥、内网地址。
- **数字要有出处**：引脚、时钟、器件型号均经真机核对；未核对项在文中显式标注。

---

## License

MIT © 2026 听心跳的声音
