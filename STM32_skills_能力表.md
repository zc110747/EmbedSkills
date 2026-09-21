# Skills 索引（全局 `~/.workbuddy/skills/`，共 18 个）

> **每个 skill 的 name + description 由宿主每会话自动注入**，本表只是速查索引，不重复描述。
> 细节一律放各 skill 的 `references/`，**按需读取，不占常驻上下文**。
> 容量约定：`SKILL.md` 正文 ≤ 6 KB（目标 2~4 KB），description ≤ 150 字符，
> 正文只留**知识点 / 判据 / 反模式 / 决策规则**。

## MCU / 嵌入式（8）

| Skill | 一句话 |
|---|---|
| `mcu-ai-agent-workflow` | 用 AI Agent 做嵌入式开发的总方法论：分阶段验收节奏、提示词要素、人工干预时机、认知误区 |
| `embedded-windows-toolchain` | Windows 上的嵌入式工具链与构建环境踩坑：构建系统、shell/编码陷阱、MSVC 手工环境 |
| `stm32-build-and-scaffold` | 工程骨架与构建系统：分层目录、CMake+Ninja、启动文件、Keil 移植、烧录与调试配置 |
| `stm32-peripherals-and-memory` | 外设驱动速查与内存架构：显示/摄像头/存储/文件系统，以及缓存与 MPU 的正确用法 |
| `mcu-debug-forensics` | 串口或板子不可用时的取证：SWD 读内存、HardFault 解码、中断链路诊断、自研探针调优 |
| `embedded-verification-acceptance` | 端到端验收方法论：双构零警告、脚本化验收、一键脚本契约、故障定位决策树 |
| `mcu-logging` | 把裸 printf 换成编译期可控的日志系统：栈缓冲、TX 中断环形缓冲、RTOS 与裸机双路径 |
| `embedded-config-portal` | 运行期配置门户：SoftAP + 内嵌网页、配置真值源、并发串行化、状态推送 |

## 显示 / GUI（1）

| Skill | 一句话 |
|---|---|
| `lvgl-font-and-render` | LVGL 静默失败排查：子集字库缺字、API 用错不报错、屏上取证、SD 卡字体引擎、初始化顺序 |

## 平台移植与平台笔记（2）

| Skill | 一句话 |
|---|---|
| `zephyr-stm32-porting` | Zephyr + STM32 移植：west 工作区、设备树 overlay、时钟树、显示与字库、Shell |
| `esp32-platform-notes` | ESP32 平台：arduino-cli 构建范式、板级硬件与烧录、Cortex-Debug 调试、链接陷阱 |

## 机器人 / 多物理场（3）

| Skill | 一句话 |
|---|---|
| `truth-source-and-model-vendoring` | 同一份真值在多处实现/多份官方模型之间漂移的取证、修法与防复发 |
| `robotics-mechanism-and-sim` | 机构几何真值取证（照片/CAD 反解）与 MuJoCo 对等实现、容差登记、判据验证 |
| `robotics-link-diagnostics` | 上位机 ↔ 机械臂链路诊断：串口/TCP/WS 传输、origin 语义、跟随抑制、验收口径 |

## SOC / 视频 / 边端 AI（1）

| Skill | 一句话 |
|---|---|
| `soc-video-and-edge-ai` | RTSP 推流 agent、流媒体服务端（WebRTC/HLS）、零依赖边缘 AI 检测跟踪管线 |

## 前端取证（1）

| Skill | 一句话 |
|---|---|
| `web-headless-verification` | 没有浏览器可用时的前端验证与 WebGL 首帧取证：打包探针、SSR 渲染探针、逐帧记录器 |

## 工具类（2）

| Skill | 一句话 |
|---|---|
| `schematic-pdf-netlist` | 从 EDA 导出的原理图 PDF 反解可读网表与引脚映射，并写成硬件规格文档 |
| `mail-weekly-digest` | 指定周期的邮箱汇总周报，产出深色极简 HTML 并预览 |

## 维护约定

- **目录布局**：`<skill>/SKILL.md` + `<skill>/references/*.md`（细节）、`<skill>/scripts/`（确定性脚本）。
- **frontmatter**：五行——`---` / `name` / `description`（≤150 字符、含触发词、第三人称）/ `agent_created: true` / `---`。
- **本次整理（2026-09-21）**：由 39 个合并为 18 个；description 总长从约 26 KB 降到约 3 KB。
  退役副本：`~/.workbuddy/skills.retired-2026-09-21/`（36 个，**零删除，可原样搬回**）。
  完整备份：`~/.workbuddy/skills.bak-2026-09-21/`。
- **跨仓镜像**：MCU 域 skill 会镜像到工程仓，同步脚本在工程侧 `support_tools/sync_skills.sh`。
  **镜像白名单写死在脚本里 —— 增删 skill 后必须同步改脚本**，否则新 skill 不会被镜像。
