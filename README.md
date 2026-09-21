# EmbedSkills

> 一位嵌入式固件工程师与 AI Agent 协作沉淀下来的 **Skill 库** —— 把「踩过的坑」写成 Agent 能直接调用的判据与配方。
>
> 当前 **18 个 Skill / 68 篇 references / 18 篇 SKILL.md（约 926 行）/ 7650 行参考资料**，全部 `agent_created: true`，与本地 `~/.workbuddy/skills/` **逐字节一致**。

<p align="left">
  <img alt="skills" src="https://img.shields.io/badge/Skills-18-2b6cb0">
  <img alt="references" src="https://img.shields.io/badge/references-68-2f855a">
  <img alt="license" src="https://img.shields.io/badge/license-MIT-718096">
  <img alt="platform" src="https://img.shields.io/badge/platform-STM32%20%7C%20ESP32%20%7C%20Zephyr-c05621">
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
| **L1 · 常驻** | `name` + `description` | **每个会话自动注入** | 18 × ≤150 字符 ≈ 3 KB |
| **L2 · 按需** | `SKILL.md` 正文（目标 2~4 KB） | 触发词命中时 | 单篇 ≈ 1/5 上下文 |
| **L3 · 精确** | `references/*.md` | 正文指向时才读那一篇 | 按需，通常 0 |

因此 `SKILL.md` 正文**只留知识点 / 判据 / 反模式 / 决策规则**，配方、完整配置、
报错对照表一律下沉到 `references/`。Skill 数量从 39 个合并为 18 个后，
常驻 description 总量从约 **26 KB 压到约 3 KB**。

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

### MCU / 嵌入式（8）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`mcu-ai-agent-workflow`](mcu-ai-agent-workflow/SKILL.md) | **L0 方法论**：AI 写嵌入式代码不难，难的是自我迭代闭环。提示词四要素、分阶段验收节奏、人工干预时机、认知误区 | 「用 AI 从零生成单片机工程」 |
| [`embedded-windows-toolchain`](embedded-windows-toolchain/SKILL.md) | Windows 主机的交叉编译（ARM GCC / ESP-IDF / Zephyr）与原生编译（MSVC + CMake/Ninja）环境搭建、构建执行、结果判据 | 「idf.py 构建」「PowerShell 输出被吞」 |
| [`stm32-build-and-scaffold`](stm32-build-and-scaffold/SKILL.md) | 工程骨架与双构建后端：目录分层、CMake+Ninja、启动文件、Keil MDK 移植、OpenOCD 烧录 | 「新建 STM32 工程」「链接报未定义 HAL 符号」 |
| [`stm32-peripherals-and-memory`](stm32-peripherals-and-memory/SKILL.md) | H7/F4 外设驱动与缓存/MPU 一致性判据：引脚映射、DCMI/SPI 屏/SD/QSPI/USB 实测坑、DMA 缓冲选址 | 「D-Cache 要不要关」「DMA 缓冲放哪」 |
| [`mcu-debug-forensics`](mcu-debug-forensics/SKILL.md) | 串口/板子不可用时的取证：SWD 读内存、HardFault 现场解码、中断链路诊断、自研 CMSIS-DAP 探针调优 | 「读内存验证变量」「探针下载慢」 |
| [`embedded-verification-acceptance`](embedded-verification-acceptance/SKILL.md) | **端到端验收方法论**：双构零警告、真机烧录/串口验证、`verify_*.py` PASS/FAIL 计数、一键脚本契约、故障定位决策树 | 「验收固件」「脚本跑不起来怎么定位」 |
| [`mcu-logging`](mcu-logging/SKILL.md) | 把裸 `printf` 换成编译期可控日志系统：单宏零成本关闭、栈缓冲避开重入、RTOS 懒互斥量 / 裸机 TX 中断环形缓冲 | 「串口打印卡死」「printf 重入」 |
| [`embedded-config-portal`](embedded-config-portal/SKILL.md) | 运行期配置门户：SoftAP + 内嵌网页、唯一真值源、读写串行化、WebSocket 快照推送、无硬件前端断言 | 「网页显示的状态不对」 |

### 显示 / GUI（1）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`lvgl-font-and-render`](lvgl-font-and-render/SKILL.md) | LVGL 渲染层**几乎不报错** —— 缺字形、值越界、区域被裁都是安静地不画。子集字库、CTF/TTF 字库引擎、初始化顺序、屏上取证 | 「字库缺字」「豆腐块」「lv_init 崩溃」 |

### 平台移植（2）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`zephyr-stm32-porting`](zephyr-stm32-porting/SKILL.md) | 裸机外设搬进 Zephyr 的差异点：west 工作区、设备树 overlay、时钟树、ST7789 点亮、GBK 点阵字库、Shell | 「ST7789 全黑」 |
| [`esp32-platform-notes`](esp32-platform-notes/SKILL.md) | Arduino CLI 与 ESP-IDF 两条构建链：构建范式、板级硬件、Cortex-Debug、组件链接陷阱 | 「openocd 报 Arg list too long」 |

### SOC / 视频 / 边端 AI（1）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`soc-video-and-edge-ai`](soc-video-and-edge-ai/SKILL.md) | 三条链路：设备侧 RTSP 推流 Agent、流媒体服务端（MediaMTX + WebRTC/HLS）、零依赖 YOLO/ByteTrack 旁路 | 「HLS 黑屏」「端侧 AI 不影响视频流」 |

### 机器人 / 多物理场（3）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`truth-source-and-model-vendoring`](truth-source-and-model-vendoring/SKILL.md) | 同一份真值在多处实现、或多份官方模型之间的**静默漂移**：冻结基线、语义核心哈希、多实现互证 | 「URDF 与 MJCF 对不上」「Sim2Sim 一致性」 |
| [`robotics-mechanism-and-sim`](robotics-mechanism-and-sim/SKILL.md) | 机构几何真值取证（照片/CAD 反解）与 MuJoCo 对等实现、容差登记、判据验证 | 「仿真没复现真机行为」 |
| [`robotics-link-diagnostics`](robotics-link-diagnostics/SKILL.md) | 上位机 ↔ 机械臂链路：串口/字节层、TCP/WS 关节级链路「谁引起谁跟随」、`origin` 语义、命令门控 | 「两条链路口径不一致」 |

### 前端取证（1）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`web-headless-verification`](web-headless-verification/SKILL.md) | 沙箱封掉 Chromium 时：esbuild 打包客户端模块打活服务、`react-dom/server` 渲染每个组件、WebGL 首帧逐帧取证 | 「页面显示 undefined 却不报错」 |

### 工具类（2）

| Skill | 解决什么 | 典型触发 |
|---|---|---|
| [`schematic-pdf-netlist`](schematic-pdf-netlist/SKILL.md) | 从 EDA 导出的原理图 PDF 反解网表与引脚映射，写成含电源树与 NC 引脚的硬件规格文档 | 「解析原理图 PDF」 |
| [`mail-weekly-digest`](mail-weekly-digest/SKILL.md) | 指定周期的邮箱汇总周报，统计收发/未读/附件并按来源归类，产出深色极简 HTML | 「邮箱周报」 |

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

### 进行中 / 计划

- [ ] **同步脚本入仓** —— 当前 `support_tools/sync_skills.sh` 在工程侧，**镜像白名单写死在脚本里**，
      增删 Skill 后必须同步改脚本，否则新 Skill 不会被镜像。计划随仓携带并把白名单改为目录自动发现。
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
