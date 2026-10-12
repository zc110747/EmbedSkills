# Skills 索引（全局 `~/.workbuddy/skills/`，共 29 个）

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

## 显示 / GUI（1）

| Skill | 一句话 |
|---|---|
| `lvgl-font-and-render` | LVGL 静默失败排查：子集字库缺字、API 用错不报错、屏上取证、SD 卡字体引擎、初始化顺序 |

## 平台移植（2）

| Skill | 一句话 |
|---|---|
| `zephyr-stm32-porting` | Zephyr + STM32 移植：west 工作区、设备树 overlay、时钟树、显示与字库、Shell |
| `esp32-platform-notes` | ESP32 平台：arduino-cli 构建范式、板级硬件与烧录、Cortex-Debug 调试、链接陷阱 |

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

## 工具类（5）

| Skill | 一句话 |
|---|---|
| `schematic-pdf-netlist` | 从 EDA 导出的原理图 PDF 反解可读网表与引脚映射，并写成硬件规格文档 |
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
