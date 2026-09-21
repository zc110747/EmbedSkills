---
name: soc-video-and-edge-ai
description: 摄像头视频链路与端侧 AI 的通用知识：RTSP 推流端可插拔后端、MediaMTX+WebRTC/HLS 服务端集成、零依赖 YOLO/ByteTrack 旁路。适用于"做 RTSP 推流 Agent""HLS 黑屏""端侧 AI 不影响视频流"等请求。
agent_created: true
---

# 摄像头视频链路与端侧 AI 分支

## 何时用

三条链路之一需要落地或排障时：设备侧 **RTSP 推流端**（Publisher）、**流媒体服务端**（把画面低延迟送到浏览器）、**端侧 AI 旁路**（在既有管线上叠加检测/跟踪）。

先划边界：推流端只做采集/编码/推送；服务端只管子进程生命周期、信令中转与 HTTP 代理，**不解码不转码**；AI 分支必须允许整条失败而不影响视频。

## 核心知识点

| 主题 | 规则 |
|---|---|
| 可插拔后端 | 采集/管线/发布均为抽象基类 + 工厂，编译期开关取值 `auto/gstreamer/sim`；`sim` 支撑无硬件 CI，换真机只换采集实现，编码/推送/接口不变 |
| 断线退避 | 退避 1/2/5/10s，耗尽后封顶不无限增长；仅当 STREAMING **稳定保持 ≥3s** 才重置退避——异步建连会造出"假 STREAMING"，把正在升级的退避清零 |
| 配置 | 优先级 CLI > 配置文件 > 内置默认；子集解析可自写，无需引第三方库 |
| 服务端拓扑 | 推流端 --RTSP--> MediaMTX --WebRTC/HLS--> 浏览器；服务端不碰媒体本身，只做 WHEP 信令代理与 HLS 反向代理 |
| 配置真值源 | MediaMTX 运行时读的是服务端**动态生成**的配置，签入的静态配置在运行时完全不生效；改运行时行为必须改生成逻辑 |
| 单端口对外 | WHEP 与 HLS 均经服务端代理，浏览器只访问一个 HTTP 端口：端口不外露、无 CORS、手机只开一个防火墙口；HLS 代理需透传会话查询参数（LL-HLS 亲和） |
| WebRTC vs HLS | WebRTC 亚秒，但怕 UDP 被挡、怕非 https 源；HLS 数秒，纯 TCP 最稳且**定位为兜底**，故绝不能给它选最脆的变体 |
| AI 旁路保证 | `tee` 分帧 + leaky queue + `drop=true` 的 appsink：AI 慢就丢帧、绝不反压视频；推理走独立线程，编码前零阻塞 |
| 语义自洽 | `frame_id` 取视频帧计数器、`timestamp` 取 PTS；用结果序号或挂钟时间会与视频时间基准脱钩 |
| 零依赖可行 | 无 OpenCV/Eigen 时 letterbox/NMS/卡尔曼/匹配均可手写（数百行级）；5fps 采样够用，CPU 推理上限约 10fps |
| 可选依赖 | 未装推理运行时也要零警告编译、视频照跑（空实现兜底） |

## 判据与反模式

- **AI 隔离判据**：关 AI / 开 AI 两次运行，帧数与码率必须一致；且关 AI 时管线描述字符串与未加 AI 时**逐字节相同**。
- 现象 → 根因：
  - 检测框乱飘 → 取 RGB 时整块 memcpy，未按 stride 逐行
  - 置信度普遍偏低 → 对已 sigmoid 的输出又做了一次 sigmoid
  - 跟踪框越收越窄直至消失 → 用固定宽高比的低维卡尔曼，宽度被外推到 0
  - 低帧率源 ID 频繁跳变 → `max_time_lost` 按 30fps 硬算，未用真实 AI 帧率
  - 改了源码行为没变 → 未重新构建，跑的是旧二进制
  - "找不到二进制" → 只探测显式路径，缺工作区内置副本与 PATH 回退
  - 重连恢复被判失败 → 读了被缓冲的 stdout 日志；判据应取实时刷盘的服务端日志
- 日志可信度：服务端日志（实时刷盘）> 推流端日志（stdout 有缓冲）> 脚本控制台（常被环境吞）。

## 详细资料

- `references/rtsp-agent.md` — 推流端接口契约、状态机、退避、单测、端到端验收
- `references/video-server.md` — MediaMTX 集成、WHEP/HLS 代理、一键脚本、沙箱诊断
- `references/edge-ai-pipeline.md` — tee 取帧、采样节拍、语义字段、构建与上报通道
- `references/yolo-onnx-decode.md` — 双布局解码、letterbox/NMS、pose、ByteTrack
- `references/acceptance.md` — 无头回归、端到端验收清单与常见假绿
