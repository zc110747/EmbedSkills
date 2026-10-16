# EmbedSkills

> 一位嵌入式固件工程师与 AI Agent 协作沉淀下来的 **Skill 库** —— 把「踩过的坑」写成 Agent 能直接调用的判据与配方。
>
> 当前 **42 个 Skill / 116 篇 references / 42 篇 SKILL.md（约 5177 行）/ 14936 行参考资料 / 12 个脚本**，全部 `agent_created: true`。
>
> ⚠️ 与本地 `~/.workbuddy/skills/` 的镜像关系当前**存在待处理的单向漂移**（本仓为超集，全局侧疑似被回退到旧快照）—— 详见 `STM32_skills_能力表.md` 的「维护约定」，**先 `--restore` 再同步**，不要直接跑 `./sync_skills.sh`。

<p align="left">
  <img alt="skills" src="https://img.shields.io/badge/Skills-42-2b6cb0">
  <img alt="references" src="https://img.shields.io/badge/references-116-2f855a">
  <img alt="scripts" src="https://img.shields.io/badge/scripts-12-805ad5">
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
│   ├── SKILL.md                # 入口：name / description(≤150字符,含触发词) / 何时用
│   ├── references/             # 细节：按需读取，不占常驻上下文
│   │   └── *.md
│   └── scripts/                # 确定性脚本（可选）：能脚本化的就别靠记忆
│       └── *.py
└── STM32_skills_能力表.md       # 速查索引
```

**三层加载模型** —— 这是整个设计里最省 token 的一环：

| 层级 | 内容 | 何时加载 | 成本 |
|---|---|---|---|
| **L1 · 常驻** | `name` + `description` | **每个会话自动注入** | 42 条 ≈ 6.2 K 字符 / **12.9 KB** |
| **L2 · 按需** | `SKILL.md` 正文（目标 2~4 KB） | 触发词命中时 | 单篇 ≈ 1/5 上下文 |
| **L3 · 精确** | `references/*.md` | 正文指向时才读那一篇 | 按需，通常 0 |

因此 `SKILL.md` 正文**只留知识点 / 判据 / 反模式 / 决策规则**，配方、完整配置、
报错对照表一律下沉到 `references/`。在 2026-09 的整理中，Skill 数量从 39 个合并为 18 个，
常驻 description 总量从约 **26 KB 压到约 3 KB**；当前共 **42 个**，常驻 42 条 description
实测 6,247 字符 / **12.9 KB**（其中 9 条已超「≤150 字符」约定，见下方待办）。

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
│ stm32-build-  │          │ embedded-       │          │ mcu-debug-      │
│ and-scaffold  │          │ verification-   │          │ forensics       │
│               │          │ acceptance      │          │                 │
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
                     │ lvgl-font-and-render  · mcu-logging     │
                     ├─────────────────────────────────────────┤
                     │ soc-video-and-edge-ai                   │
                     │ robotics-mechanism-and-sim              │
                     │ robotics-link-diagnostics               │
                     │ web-headless-verification               │
                     ├─────────────────────────────────────────┤
                     │ schematic-pdf-netlist · mail-weekly-    │
                     │ digest                                  │
                     └─────────────────────────────────────────┘
```

---

## Skill 清单

### MCU / 嵌入式（12）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`mcu-ai-agent-workflow`](mcu-ai-agent-workflow/SKILL.md) | **L0 方法论**：AI 写嵌入式代码不难，难的是自我迭代闭环。提示词四要素、分阶段验收节奏、人工干预时机、认知误区 | 「用 AI 从零生成单片机工程」 |
| [`embedded-windows-toolchain`](embedded-windows-toolchain/SKILL.md) | Windows 主机的交叉编译（ARM GCC / ESP-IDF / Zephyr）与原生编译（MSVC + CMake/Ninja）环境搭建、构建执行、结果判据 | 「idf.py 构建」「PowerShell 输出被吞」 |
| [`stm32-build-and-scaffold`](stm32-build-and-scaffold/SKILL.md) | 工程骨架与双构建后端：目录分层、CMake+Ninja、启动文件、Keil MDK 移植、OpenOCD 烧录 | 「新建 STM32 工程」「链接报未定义 HAL 符号」 |
| [`stm32-peripherals-and-memory`](stm32-peripherals-and-memory/SKILL.md) | H7/F4 外设驱动与缓存/MPU 一致性判据：引脚映射、DCMI/SPI 屏/SD/QSPI/USB 实测坑、DMA 缓冲选址 | 「D-Cache 要不要关」「DMA 缓冲放哪」 |
| [`mcu-debug-forensics`](mcu-debug-forensics/SKILL.md) | 串口/板子不可用时的取证：SWD 读内存、HardFault 现场解码、中断链路诊断、自研 CMSIS-DAP 探针调优 | 「读内存验证变量」「探针下载慢」 |
| [`embedded-verification-acceptance`](embedded-verification-acceptance/SKILL.md) | **端到端验收方法论**：双构零警告、真机烧录/串口验证、`verify_*.py` PASS/FAIL 计数、一键脚本契约、故障定位决策树 | 「验收固件」「脚本跑不起来怎么定位」 |
| [`mcu-logging`](mcu-logging/SKILL.md) | 把裸 `printf` 换成编译期可控日志系统：单宏零成本关闭、栈缓冲避开重入、RTOS 懒互斥量 / 裸机 TX 中断环形缓冲 | 「串口打印卡死」「printf 重入」 |
| [`mcu-code-style`](mcu-code-style/SKILL.md) | **自研 C 代码规范**：文件级静态变量合并为结构体（同一件事才合并）、按暴露数量选接口粒度、只读返回 `const` 指针、注释摘要化、第三方代码不动只上报 | 「静态变量怎么组织」「变量怎么对外暴露」「注释太长」 |
| [`mcu-code-style-apply`](mcu-code-style-apply/SKILL.md) | **mcu-code-style 落地施工**：把规范批量应用到既有 STM32/嵌入式工程——clang-format 配置、GBK 编码保护、生成文件豁免、目录大小写改名、static 合并、MDK/GCC 双构建验证与提交拆分 | 「给某工程应用 code style」「按新规范更新老项目」 |
| [`mcu-cpp-development`](mcu-cpp-development/SKILL.md) | 用 C++ 写单片机的代码方法与格式：C/C++ 混合链接与 `extern "C"`、模板 + `constexpr` 零成本外设封装、`new/delete` 重载、Makefile 双编译 | 「C++ 开发单片机」「混合编译」「undefined reference 函数重载」 |
| [`embedded-config-portal`](embedded-config-portal/SKILL.md) | 运行期配置门户：SoftAP + 内嵌网页、唯一真值源、读写串行化、WebSocket 快照推送、无硬件前端断言 | 「网页显示的状态不对」 |
| [`avr-flash-ram`](avr-flash-ram/SKILL.md) | AVR(avr-gcc/avr-libc) RAM 溢出：字符串字面量默认进 .data 挤爆栈，致固件空载正常、收命令即复位。avr-size/nm/objdump 定位、PSTR/PROGMEM 正解、%S 与 %s 区别 | 「AVR 收命令复位」「.data 异常大」 |

### 显示 / GUI（2）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`lvgl-font-and-render`](lvgl-font-and-render/SKILL.md) | LVGL 渲染层**几乎不报错** —— 缺字形、值越界、区域被裁都是安静地不画。子集字库、CTF/TTF 字库引擎、初始化顺序、屏上取证 | 「字库缺字」「豆腐块」「lv_init 崩溃」 |
| [`lvgl9-mcu-porting`](lvgl9-mcu-porting/SKILL.md) | **v8 → v9 破坏性变化**与裸机移植陷阱：`LV_TICK_CUSTOM` 被删（首屏冻结）、`lv_color_hex` 改 RGB888、静态库 vs section 表、启动画面/动作条与多屏交接、`file(GLOB)` 不追踪新文件 | 「v8 升 v9 后首屏冻结」「复位彩条」「多屏切换」 |

### 平台移植（4）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`zephyr-stm32-porting`](zephyr-stm32-porting/SKILL.md) | 裸机外设搬进 Zephyr 的差异点：west 工作区、设备树 overlay、时钟树、ST7789 点亮、GBK 点阵字库、Shell | 「ST7789 全黑」 |
| [`esp32-platform-notes`](esp32-platform-notes/SKILL.md) | Arduino CLI 与 ESP-IDF 两条构建链：构建范式、板级硬件、Cortex-Debug、组件链接陷阱 | 「openocd 报 Arg list too long」 |
| [`ra8d1-fsp-platform-notes`](ra8d1-fsp-platform-notes/SKILL.md) | Renesas RA8D1（R7FA8D1BH / Cortex-M85 + FSP）平台经验：内存映射、GLCDC/RGB 与 MIPI DSI、xSPI/OSPI 串行 Flash、PFS 引脚复用 | 「RA8D1 显屏不出图」「OSPI CS 通道」 |
| [`ra8d1-vscode-pyocd-debug`](ra8d1-vscode-pyocd-debug/SKILL.md) | 官方 target 缺失时，在 VSCode + CMSIS-DAP 上给 RA8D1 搭源码级调试：pyOCD 无 target 的绕过路径 | 「RA8D1 无法调试」「pyocd 报 no target」 |

### SOC / 视频 / 边端 AI（1）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`soc-video-and-edge-ai`](soc-video-and-edge-ai/SKILL.md) | 三条链路：设备侧 RTSP 推流 Agent、流媒体服务端（MediaMTX + WebRTC/HLS）、零依赖 YOLO/ByteTrack 旁路 | 「HLS 黑屏」「端侧 AI 不影响视频流」 |

### 上位机应用层 / C++20 协程（3）

**非固件**方向：宿主侧 C++20 运行时、单线程网络服务、大规模客户端验收。前缀 `app-`。

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`app-cpp20-coroutine-runtime`](app-cpp20-coroutine-runtime/SKILL.md) | 单线程协作式协程运行时的**静默失败**：五条不变量、generation 计数唤醒协议（替代锁、根治双重 resume）、帧归属与进程级泄漏断言、取消是状态不是信号、header-only 的 inline/ODR 漏网、定时器堆惰性删除、通道背压 | 「C++20 协程」「co_await 卡住」「双重 resume」「协程帧泄漏」「header-only 重复符号」 |
| [`app-select-relay-server`](app-select-relay-server/SKILL.md) | 单线程 `select()` 服务的规模上限与可移植性：Windows `FD_SETSIZE=64` 令 `FD_SET` **静默截断**（能连上、被计入在线、数据被无声丢弃）、`listen` 必须非阻塞、`backlog` 要覆盖 accept 节奏、错误文本本地化破坏纯 ASCII 契约 | 「客户端一多就丢数据」「连接被拒」「accept 挂死」 |
| [`app-host-load-acceptance`](app-host-load-acceptance/SKILL.md) | 多客户端规模压测与验收：参数化 N 客户端 harness、断言前先等前置条件、stats 基线防读旧行、包边界与字节相等**分层断言**、聚合恒等式做无损证明、**负向对照证明脚本有牙齿** | 「压测脚本」「1000 客户端」「负载验收」「测试恒绿或 flaky」 |

### 机器人 / 多物理场（5）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`truth-source-and-model-vendoring`](truth-source-and-model-vendoring/SKILL.md) | 同一份真值在多处实现、或多份官方模型之间的**静默漂移**：冻结基线、语义核心哈希、多实现互证 | 「URDF 与 MJCF 对不上」「Sim2Sim 一致性」 |
| [`robotics-mechanism-and-sim`](robotics-mechanism-and-sim/SKILL.md) | 机构几何真值取证（照片/CAD 反解）与 MuJoCo 对等实现、容差登记、判据验证 | 「仿真没复现真机行为」 |
| [`robotics-link-diagnostics`](robotics-link-diagnostics/SKILL.md) | 上位机 ↔ 机械臂链路：串口/字节层、TCP/WS 关节级链路「谁引起谁跟随」、`origin` 语义、命令门控 | 「两条链路口径不一致」 |
| [`arm-photo-texturing`](arm-photo-texturing/SKILL.md) | 实拍照片给刚体/机械臂模型贴真实纹理（Level3→4 视觉增强，非几何重建）：大面法向判定、拍摄协议、四角定位、透视校正、three.js 按面材质与 envMap | 「照片贴图」「透视校正」「数字孪生视觉增强」 |
| [`motor-telemetry-alias-proof`](motor-telemetry-alias-proof/SKILL.md) | 读数上蹿下跳到底是欠采样旋转波形、真噪声还是饱和钳位：按相位分箱看离散度塌缩，配物理律/链路闭合/混叠比三判据 | 「PWM/相电流跳动」「波形像噪声」「数据在抖是 bug 还是采样」 |

### 前端 / Windows GUI 取证（3）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`web-headless-verification`](web-headless-verification/SKILL.md) | 沙箱封掉 Chromium 时：esbuild 打包客户端模块打活服务、`react-dom/server` 渲染每个组件、WebGL 首帧逐帧取证 | 「页面显示 undefined 却不报错」 |
| [`win-gui-screenshot-verify`](win-gui-screenshot-verify/SKILL.md) | Windows 桌面 GUI(SDL/LVGL/Qt) 零依赖自动化视觉验收：ctypes+BitBlt 抓客户区、DPI 感知点击、纯 Python PNG 裁剪放大、单调用编排 | 「GUI 截图」「自动化验收」「点击没反应」「DPI 缩放」 |
| [`wpf-realtime-sim`](wpf-realtime-sim/SKILL.md) | WPF+MVVM 实时仿真/遥测看板：解耦后台步进线程、30FPS 刷新、自更新 Canvas 趋势图、暗色主题(含 ComboBox 模板)、离屏 PNG 验证 | 「WPF 实时仿真」「无图表库趋势图」「暗色 ComboBox」 |

### 工具类（6）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`schematic-pdf-netlist`](schematic-pdf-netlist/SKILL.md) | 从 EDA 导出的原理图 PDF 反解网表与引脚映射，写成含电源树与 NC 引脚的硬件规格文档 | 「解析原理图 PDF」 |
| [`pyocd-flm-inject-debug`](pyocd-flm-inject-debug/SKILL.md) | 芯片无内建 pyOCD target、或 pack target 在 CMSIS-DAP 上初始化失败时：用 `pyocd_user.py` 的 `will_init_target` 钩子注入 memory map + 官方 FLM 闪存算法 | 「pyocd 烧不了」「cortex-debug 连不上」 |
| [`mail-weekly-digest`](mail-weekly-digest/SKILL.md) | 指定周期的邮箱汇总周报，统计收发/未读/附件并按来源归类，产出深色极简 HTML | 「邮箱周报」 |
| [`deterministic-clock-testing`](deterministic-clock-testing/SKILL.md) | 把时间抽象成可注入 TimerLike+FakeTimer，让依赖延迟/节流/超时/重试的代码可确定性测试（无真实 sleep）：最小接口、FakeTimer 四要点、四类断言 | 「定时器测试」「节流测试」「flaky 测试」「假时钟」 |
| [`git-silent-source-loss`](git-silent-source-loss/SKILL.md) | 源文件凭空消失/换机编译不过：.gitignore 误匹配源文件 + git add 静默跳过。三步定位、修复(!例外+注释)、类案清单 | 「文件不见了」「git add 不生效」「clone 缺文件」 |
| [`win-batch-sandbox-probe`](win-batch-sandbox-probe/SKILL.md) | Windows 批处理坑与沙箱等效验证：块内 echo 裸括号提前闭合、Python subprocess 真跑 .bat、进程树回收、shell 追加重写覆盖、file-history 救援 | 「bat 报 此时不应有 or」「沙箱跑 bat」「追加没生效」 |

---

## 跨 Skill 的复用链

Skill 之间**显式互相引用**，常用组合：

| 场景 | 调用链 |
|---|---|
| **从零做一个 MCU 工程** | `mcu-ai-agent-workflow` → `stm32-build-and-scaffold` → `embedded-windows-toolchain` → `embedded-verification-acceptance` |
| **板子「像死了」** | `mcu-debug-forensics`（先定性） → `stm32-peripherals-and-memory`（查缓存/MPU） → `mcu-logging`（补可观测性） |
| **屏上显示不对** | `lvgl-font-and-render` → `stm32-peripherals-and-memory`（屏/总线） → `zephyr-stm32-porting`（若走 RTOS） |
| **给设备加网页配置** | `embedded-config-portal` → `web-headless-verification`（无硬件验证前端） → `embedded-verification-acceptance` |
| **改机构参数前** | `robotics-mechanism-and-sim`（量真值） → `truth-source-and-model-vendoring`（防漂移） → `robotics-link-diagnostics`（验链路） |
| **做一个上位机网络服务** | `app-cpp20-coroutine-runtime`（事件循环若是协程调度器） → `app-select-relay-server`（规模上限与运维契约） → `app-host-load-acceptance`（压测验收） |
| **服务「客户端一多就丢数据」** | `app-select-relay-server`（`FD_SET` 截断 / `backlog`） → `app-host-load-acceptance`（复现 + 负向对照） |

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

- **纯 Linux 应用开发者** —— 只有 `web-headless-verification`、`truth-source-and-model-vendoring`
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
description ≤ 150 字符，含触发词，第三人称
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
```

纳管范围**目录自动发现**（全局 skills 下每个顶层 skill 目录 + 顶层 `.md`），仅排除
`README.md` / `.git` / `.workbuddy` —— 刻意**不做写死白名单**：旧版把 18 个名字硬编码，
skill 改名/合并后清单全部失效、静默漏同步（2026-09-30 实测 18 个名字里 16 个已不存在）。

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

### 进行中 / 计划

- [ ] **解掉镜像漂移（优先）** —— 全局 `~/.workbuddy/skills/` 比本仓**少 15 个 skill**
      （疑似被回退到 2026-09 的旧快照），且 `web-headless-verification/SKILL.md` 与
      `STM32_skills_能力表.md` 的全局副本更旧。正确顺序：先 `./sync_skills.sh --restore`
      （镜像 → 全局），再 `./sync_skills.sh --check` 应得 `RESULT: IDENTICAL`。
      ⚠️ 在此之前**不要**直接跑 `./sync_skills.sh` —— 它会用全局的旧副本覆盖镜像的新副本。
- [ ] **收敛超长 description** —— 实测 9 篇超出「≤150 字符」约定
      （`ra8d1-fsp-platform-notes` 441 / `pyocd-flm-inject-debug` 276 / `lvgl9-mcu-porting` 224 /
      `replica-mock-harness` 216 / `ra8d1-vscode-pyocd-debug` 204 / `stm32-build-and-scaffold` 194 /
      `replica-memory-engine` 179 / `replica-recon` 161 / `mcu-code-style-apply` 156），
      42 条常驻共 12.9 KB，压缩后可省下一半常驻成本。
- [ ] **安装脚本** —— 让「全量安装」从手抄 `for` 循环变成 `install.sh` / `install.bat`（Windows 侧纯 ASCII、pause-on-error）。
- [ ] **CI 一致性校验** —— 提交时校验 frontmatter 完整性、description 字符数、`references/` 链接有效性。
- [ ] **领域扩展** —— 边缘 AI 部署（ONNX / CMSIS-NN 量化链路）、嵌入式 Linux SOC（RK3568 摄像头/RTSP）方向仍偏薄。

---

## 维护约定

- **目录布局**：`<skill>/SKILL.md` + `references/*.md`（细节）、`scripts/`（确定性脚本）。
- **frontmatter 五行**：`---` / `name` / `description`（≤150 字符、含触发词、第三人称）/ `agent_created: true` / `---`。
- **零删除原则**：整理时旧版本整体退役到带日期的备份目录，可原样搬回。
- **不写敏感信息**：本仓不含任何 token、凭据、密钥、内网地址。
- **数字要有出处**：引脚、时钟、器件型号均经真机核对；未核对项在文中显式标注。

---

## License

MIT © 2026 听心跳的声音
