# Skills 索引（全局 `~/.workbuddy/skills/`，本表列 42 个）

> **每个 skill 的 name + description 由宿主每会话自动注入**，本表只是速查索引，不重复描述。
> 细节一律放各 skill 的 `references/`，**按需读取，不占常驻上下文**。
> 容量约定：`SKILL.md` 正文 ≤ 6 KB（目标 2~4 KB），description ≤ 150 字符，
> 正文只留**知识点 / 判据 / 反模式 / 决策规则**。

## MCU / 嵌入式（12）

| Skill | 一句话 |
|---|---|
| `mcu-ai-agent-workflow` | 用 AI Agent 做嵌入式开发的总方法论：分阶段验收节奏、提示词要素、人工干预时机、认知误区 |
| `embedded-windows-toolchain` | Windows 上的嵌入式工具链与构建环境踩坑：构建系统、shell/编码陷阱、MSVC 手工环境 |
| `stm32-build-and-scaffold` | 工程骨架与构建系统：分层目录、CMake+Ninja、启动文件、Keil 移植、烧录与调试配置 |
| `stm32-peripherals-and-memory` | 外设驱动速查与内存架构：显示/摄像头/存储/文件系统，以及缓存与 MPU 的正确用法 |
| `mcu-code-style` | 自研 C 代码规范：文件级静态变量合并为结构体、按数量选对外接口粒度、注释摘要化、第三方代码不动 |
| `mcu-code-style-apply` | 把 mcu-code-style 批量应用到既有 STM32/嵌入式的施工流程：clang-format、GBK 保护、生成文件豁免、目录大小写改名、static 合并、MDK/GCC 双构建验证与提交拆分 |
| `mcu-cpp-development` | C++ 写单片机的代码方法与格式：C/C++ 混合链接、模板+constexpr 零成本外设封装、new/delete 重载 |
| `mcu-debug-forensics` | 串口或板子不可用时的取证：SWD 读内存、HardFault 解码、中断链路诊断、自研探针调优 |
| `embedded-verification-acceptance` | 端到端验收方法论：双构零警告、脚本化验收、一键脚本契约、故障定位决策树 |
| `mcu-logging` | 把裸 printf 换成编译期可控的日志系统：栈缓冲、TX 中断环形缓冲、RTOS 与裸机双路径 |
| `embedded-config-portal` | 运行期配置门户：SoftAP + 内嵌网页、配置真值源、并发串行化、状态推送 |
| `avr-flash-ram` | AVR(avr-gcc/avr-libc) RAM 溢出：字符串字面量默认进 .data 挤爆栈致收命令即复位；avr-size/nm/objdump 定位、PSTR/PROGMEM 正解、%S 与 %s 区别 |

## 显示 / GUI（2）

| Skill | 一句话 |
|---|---|
| `lvgl-font-and-render` | LVGL 静默失败排查：子集字库缺字、API 用错不报错、屏上取证、SD 卡字体引擎、初始化顺序 |
| `lvgl9-mcu-porting` | LVGL v8→v9 破坏性变化与裸机移植：tick 回调被删致首屏冻结、`lv_color_hex` 改 RGB888、静态库 vs section 表、启动画面与多屏交接、`file(GLOB)` 漏新文件 |

## 平台移植（4）

| Skill | 一句话 |
|---|---|
| `zephyr-stm32-porting` | Zephyr + STM32 移植：west 工作区、设备树 overlay、时钟树、显示与字库、Shell |
| `esp32-platform-notes` | ESP32 平台：arduino-cli 构建范式、板级硬件与烧录、Cortex-Debug 调试、链接陷阱 |
| `ra8d1-fsp-platform-notes` | Renesas RA8D1（Cortex-M85 + FSP）：内存映射、GLCDC/MIPI DSI、RTC 计数源、PFS 写保护、xSPI/OSPI（CS 通道与 `BMCTL0` 陷阱）、Cache/MPU、SWD 取证方法论 |
| `ra8d1-vscode-pyocd-debug` | 官方 target 缺失时给 RA8D1 搭 VSCode 源码级调试：pyOCD 通用 `cortex_m` + 内存映射注入 |

## 机器人 / 多物理场（5）

| Skill | 一句话 |
|---|---|
| `truth-source-and-model-vendoring` | 同一份真值在多处实现/多份官方模型之间漂移的取证、修法与防复发 |
| `robotics-mechanism-and-sim` | 机构几何真值取证（照片/CAD 反解）与 MuJoCo 对等实现、容差登记、判据验证 |
| `robotics-link-diagnostics` | 上位机 ↔ 机械臂链路诊断：串口/TCP/WS 传输、origin 语义、跟随抑制、验收口径 |
| `arm-photo-texturing` | 实拍照片给刚体/机械臂模型贴真实纹理（Level3→4 视觉增强，非几何重建）：大面法向判定、拍摄协议、四角定位、透视校正、three.js 按面材质与 envMap |
| `motor-telemetry-alias-proof` | 读数上蹿下跳到底是欠采样旋转波形、真噪声还是饱和钳位：按相位分箱看离散度塌缩，配物理律/链路闭合/混叠比三判据 |

## SOC / 视频 / 边端 AI（1）

| Skill | 一句话 |
|---|---|
| `soc-video-and-edge-ai` | RTSP 推流 agent、流媒体服务端（WebRTC/HLS）、零依赖边缘 AI 检测跟踪管线 |

## 前端 / Windows GUI 取证（3）

| Skill | 一句话 |
|---|---|
| `web-headless-verification` | 没有浏览器可用时的前端验证与 WebGL 首帧取证：打包探针、SSR 渲染探针、逐帧记录器、canvas 像素跨度取证 |
| `win-gui-screenshot-verify` | Windows 桌面 GUI(SDL/LVGL/Qt) 零依赖自动化视觉验收：ctypes+BitBlt 抓客户区、DPI 感知点击、纯 Python PNG 裁剪放大、单调用编排 |
| `wpf-realtime-sim` | WPF+MVVM 实时仿真/遥测看板：解耦后台步进线程、30FPS 刷新、自更新 Canvas 趋势图、暗色主题、离屏 PNG 验证 |

## 上位机桌面应用（.NET / C#）（2）

| Skill | 一句话 |
|---|---|
| `winforms-desktop-app` | C#/.NET WinForms 桌面应用：自绘圆角控件的 DPI 与裁剪、NAudio 3.x 播放器生命周期与无音频设备处理、外部 CLI 集成、同一个 exe 兼作命令行工具（`AttachConsole` 顺序陷阱）、运行期条件跳过的测试与发布 |
| `piper-offline-tts` | Piper 本地离线 TTS 集成：CLI 契约（正文走 stdin、输出用 -f）、长文本无实际上限的实测方法、喂给 TTS 前的文本准备（章节抽取 / 仅接受 UTF-8 / 非目标语言闸门）、运行时与模型的获取及哈希/许可核对、WAV 原子落地与解码校验 |

## 上位机应用层（C++20 协程 / 网络服务 / 压测）（3）

| Skill | 一句话 |
|---|---|
| `app-cpp20-coroutine-runtime` | 单线程协作式协程运行时的静默失败：五条不变量、generation 唤醒协议、协程帧归属与泄漏断言、取消是状态、header-only 的 inline/ODR、定时器堆惰性删除、通道背压 |
| `app-select-relay-server` | 单线程 `select()` 服务的规模上限：Windows `FD_SETSIZE=64` 让 `FD_SET` 静默截断、`listen` 必须非阻塞、`backlog` 与 accept 节奏、错误文本本地化破坏纯 ASCII 契约 |
| `app-host-load-acceptance` | 多客户端规模压测验收：参数化 N 客户端 harness、断言前先等前置条件、stats 基线、包边界与字节相等分层断言、聚合恒等式、负向对照证明脚本有牙齿 |

## 复刻（逆向 → 替身 → 复现）（4）

| Skill | 一句话 |
|---|---|
| `replica-recon` | 复刻第一步逆向取证：原件身份与版本、PE/容器静态解析、资源与字符串挖掘、行为观察，结论按证据强度分级 |
| `replica-memory-engine` | 外部读写目标进程内存的引擎：符号解析、AOB 签名扫描、多级指针链、位域读写、写后回读、代码洞与跳板 hook、x64 指令长度解码 |
| `replica-mock-harness` | 替身进程验收：没有目标程序时验证「读地址→指针链→写值→回读」整条接线，PASS/FAIL/SKIP 三分类把「环境缺位点」与「接线坏了」分开 |
| `replica-ui-fidelity` | 从参考截图逐像素反推复刻界面：布局度量标定、DPI 缩放、字号实测标定、色值采样、自绘控件与真实子窗口遮挡、像素级复验 |

## 工具类（6）

| Skill | 一句话 |
|---|---|
| `schematic-pdf-netlist` | 从 EDA 导出的原理图 PDF 反解可读网表与引脚映射，并写成硬件规格文档 |
| `pyocd-flm-inject-debug` | 芯片无 pyOCD 内建 target / pack target 在 DAP 上初始化失败：`pyocd_user.py` 钩子注入 memory map + FLM，打通烧录与 cortex-debug |
| `mail-weekly-digest` | 指定周期的邮箱汇总周报，产出深色极简 HTML 并预览 |
| `deterministic-clock-testing` | 把时间抽象成可注入 TimerLike+FakeTimer，让依赖延迟/节流/超时/重试的代码可确定性测试（无真实 sleep） |
| `git-silent-source-loss` | 源文件凭空消失/换机编译不过：.gitignore 误匹配源文件 + git add 静默跳过；三步定位、修复(!例外+注释)、类案清单 |
| `win-batch-sandbox-probe` | Windows 批处理坑与沙箱等效验证：块内 echo 裸括号提前闭合、Python subprocess 真跑 .bat、进程树回收、shell 追加重写覆盖、file-history 救援 |

## 维护约定

- **目录布局**：`<skill>/SKILL.md` + `<skill>/references/*.md`（细节）、`<skill>/scripts/`（确定性脚本）。
- **frontmatter**：五行——`---` / `name` / `description`（≤150 字符、含触发词、第三人称）/ `agent_created: true` / `---`。
- **本次整理（2026-09-21）**：由 39 个合并为 18 个；description 总长从约 26 KB 降到约 3 KB。
  退役副本：`~/.workbuddy/skills.retired-2026-09-21/`（36 个，**零删除，可原样搬回**）。
  完整备份：`~/.workbuddy/skills.bak-2026-09-21/`。
- **2026-09-30**：`mcu-comment-style` **改名并扩写为 `mcu-code-style`**（纳入"文件级静态状态封装"
  与"第三方边界"两条规则）。旧名已不存在，引用请统一用新名。
- **2026-09-30（晚）**：C 类 8 个系统独有 skill 并入本仓并统一（去项目路径/旧名/commit 哈希、提知识点）：
  `arm-photo-texturing` / `avr-flash-ram` / `deterministic-clock-testing` / `motor-telemetry-alias-proof` /
  `win-gui-screenshot-verify` / `wpf-realtime-sim` / `git-silent-source-loss` / `win-batch-sandbox-probe`；
  B4 `webui-canvas-pixel-assert` 独有段并入 `web-headless-verification/references/canvas-pixel-assert.md`；
  补登此前漏列的 `mcu-code-style-apply`。索引现 **29 个**（本表与 README 已对齐）。
- **跨仓镜像**：本仓即全局 `~/.workbuddy/skills/` 的唯一版本化镜像，同步脚本在**本仓** `sync_skills.sh`，
  纳管清单**目录自动发现**（不再写死白名单，改名/合并后不会静默漏同步）。
- **2026-10-16**：新增上位机桌面应用类 2 个 skill（`winforms-desktop-app`、`piper-offline-tts`，
  来源：EnglishAudio 本地离线英语语音工具）。本表所列由 29 → **31**。
- **2026-10-16（补）**：该工程追加命令行模式后，给上面 2 个 skill 各加 1 篇 references
  （`gui-exe-as-cli` / `text-prep-for-tts`），skill 数不变、references 116 → **118**。
- **2026-10-19（已解决）**：此前记录的「镜像比全局多 15 个 skill」漂移**已消除**——
  全局 `~/.workbuddy/skills/` 被回退到 2026-09 旧快照，用 `--restore` + 增量补齐后
  `--check` 得 `RESULT: IDENTICAL`（42 skill + 1 文件）。全局侧修复前已整份备份到
  `~/.workbuddy/skills.bak-20261019/`。
  - 同时**修掉 `sync_skills.sh` 的设计缺口**：纳管清单原先只扫全局，导致 `--restore`
    永远补不上「全局缺、镜像有」的目录（当时只能手动 `cp` 15 个目录）。现改为**两侧都扫再取并集**，
    `--restore` 可一次收敛。`--check` 的输出也改为自解释的
    `[仅全局存在→需 sync]` / `[仅镜像存在→需 restore]`。
  - 新增仓根 `lint_skills.py`（零依赖）：校验 frontmatter 闭合、`name` == 目录名、
    `description ≤ 150`、`agent_created: true`、正文首行 H1、`references/` 链接有效性（含跨 skill 引用）。
  - ⚠️ **改动的落点别搞反**：本次先在镜像侧改、随后跑 `sync`，结果被全局旧副本**反向覆盖**，
    只能重做。正确顺序是「**先改全局** → `sync` 到镜像 → 能力表等仓独有文件再 `cp` 回全局」。
- **2026-10-19（瘦身）**：11 篇 `description` 超 150 字符的一律压到 **≤150**，
  42 条常驻总量 **6,328 → 5,427 字符**（约省 14%）；顺带补齐 3 篇缺失的
  `agent_created: true`（`lvgl9-mcu-porting` / `mcu-code-style-apply` / `ra8d1-vscode-pyocd-debug`），
  并为能力表补登此前漏列的 11 个 skill（31 → **42**）。
