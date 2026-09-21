# 流媒体服务端（Go + MediaMTX + WebRTC/HLS）细节

目标：把一台设备（或它的主机仿真器）的摄像头画面**低延迟推到浏览器（主机 + 手机）**。服务端自己**不解码不转码**，只做子进程生命周期管理、配置生成、信令中转与 HTTP 代理。

## 架构全景

```
 采集端(推流器)                 MediaMTX               流媒体服务端(Go)            Browser
 (GStreamer RTSP publisher) ──RTSP──▶ (子进程)  ──control API──▶ HTTP :<api-port>
        │                                │  WebRTC :<webrtc-port>      │  /api/cameras/{id}/webrtc  (WHEP 代理)
        │                                │  HLS    :<hls-port>         │  /hls/{stream}/{file}       (反向代理)
        │                                └────────────────────────────┘
        └── 发布 rtsp://<host>:<rtsp-port>/<stream> ─────────────────────────────▶  WebRTC(亚秒) / HLS(兜底)
```

| 组件 | 职责 | 关键位置 |
|---|---|---|
| 服务端 (Go) | HTTP API、媒体服务器生命周期管理、WebRTC 信令代理、HLS 反向代理、摄像头注册/发现、健康检查 | `cmd/<svc>/main.go`、`internal/server`、`internal/<media>/manager.go`、`internal/api/*` |
| MediaMTX（子进程） | 媒体服务器：RTSP 收流 + WebRTC/HLS 出流，**由服务端拉起并写动态配置** | `internal/<media>/manager.go` 的 `GenerateConfig()` |
| 推流端（C++/GStreamer） | RTSP Publisher；换真机只换采集源 | 见 `rtsp-agent.md` |
| 前端（Vue3+Vite+hls.js） | WebRTC 优先，超时后自动切 HLS 兜底 | `web/src/.../player.ts`、`VideoPlayer.vue` |

## MediaMTX 集成要点

### 二进制定位：三级回退

1. 配置里的显式路径（Windows 自动补 `.exe`）
2. 工作区内置副本（`./<media>/<binary>(.exe)`）
3. `exec.LookPath("<binary>")`（系统 PATH）

> 只对配置值做 `os.Stat` 会误报"binary not found"；三级回退后只要在 PATH 里即可启动。**改了源码必须重新构建**，否则跑的是旧 exe。

### 每次启动动态生成配置

- 端口（RTSP / WebRTC / HLS / API / ICE）以服务端配置文件为**单一事实来源**，写入运行时目录的临时配置文件名，避免覆盖签入文件。
- **关键认知：运行时用的是动态生成的配置，不是签入的静态配置文件。** 静态文件里的项（如 `hlsVariant: lowLatency`）在运行时**完全不生效**；要改媒体服务器运行时行为，必须改 `GenerateConfig()` 里的格式化字符串。
- 关掉 `rtmp/srt/moq`，只留 RTSP/WebRTC/HLS：少开监听口，否则第二个实例起不来。
- WebRTC 必须开 `webrtcLocalTCPAddress`（ICE over TCP）：手机 Wi-Fi 常挡 UDP，这是"桌面能播、手机黑屏"的经典根因之一。

### WebRTC 信令代理（WHEP）

`POST /api/cameras/{id}/webrtc` → 把 SDP offer 转发到媒体服务器 `http://127.0.0.1:<webrtc-port>/{path}/whep`，回传 answer。浏览器只跟服务端单一 HTTP 端口打交道 ⇒ WebRTC 端口不对外暴露、无 CORS 问题。

### HLS 反向代理

`GET /hls/{stream}/{file}` → `http://127.0.0.1:<hls-port>/{stream}/{file}`。同域、单端口、纯 TCP，手机只需开一个防火墙口。必须透传 `?session=` 查询参数（LL-HLS 会话亲和）。

## WebRTC vs HLS 决策

| | WebRTC | HLS |
|---|---|---|
| 延迟 | 亚秒 | 数秒（LL-HLS 更低但仍 >1s） |
| 传输 | UDP（+TCP ICE） | 纯 HTTP/TCP |
| 手机痛点 | Wi-Fi 挡 UDP/ICE；iOS Safari 在非 https 源拒绝 WebRTC | 无（纯 TCP + 原生支持） |
| 角色 | 默认优先 | **兜底** |

前端：WebRTC 起手，超时（约 7s）无帧 → 切 HLS；iOS Safari 走原生 HLS（`canPlayType('application/vnd.apple.mpegurl')`）。

> 设计意图：**HLS 必须是最稳的那条路**，因为它专门用来救 WebRTC 失败的手机。所以 HLS 绝不能选最脆的变体。

### HLS 黑屏根因（真实 Bug 模式）

链路"WebRTC 通、HLS 两端黑屏"的典型成因链：运行时配置未钉住 `hlsVariant` → 落到默认的 lowLatency 变体 → 缺片时的占位对象以 `text/html` 返回 → hls.js 视为致命错误、整条 HLS 挂掉。

判据与排查顺序：
1. 确认改的是**生成配置**而不是静态文件（静态文件不生效，容易白改）。
2. 对比**代理地址**与**直连地址**：两者一致 ⇒ 媒体服务器问题；不一致 ⇒ 代理问题。
3. 检查分片响应头 `Content-Type`，出现 `text/html` 即命中此模式。

## 一键脚本与前端嵌入

| 脚本 | 作用 |
|---|---|
| 全量构建 | 预检（go/node/编译器）→ 前端 `npm install`(自愈) + `npm run build` → 服务端 `go build` → 调推流端构建 → 汇总。失败路径打印 `reason`/`hint` 并可 `pause`；`--no-pause` 供 CI |
| 一键启动 | 挑最新产物 exe → 解析/校验配置 → 清残留进程 → 分离启动（日志落盘）→ 轮询健康检查接口（约 40s）。LAN 地址取自服务端地址查询接口 |
| 联合启动 | 同时拉起服务端 + 媒体服务器 + 推流端；含"源码比产物新则自动重建"防复发 |

> 防复发铁律：**改 Go 源码后必须 `go build`**，否则跑旧 exe（典型误判：二进制明明在 PATH 里却报"找不到"——其实是 exe 是改源码前的旧版）。联合启动脚本自动比对 mtime 重建。

> **前端资源常被 `go:embed` 嵌进二进制（不是磁盘直出）**：`//go:embed all:dist` + `fs.Sub(webstatic.Dist,"dist")`。因此任何前端改动都必须两步走：先在前端目录 `npm run build` 产出 dist，**再** `go build` 把新 dist 嵌进 exe，最后重启服务。只改 Go 也要 `go build`（无需 npm）。误记为"磁盘直出、改前端不用 npm"会导致改了前端网页纹丝不动。验证嵌入：`grep <新bundlehash> <svc>.exe`。

## 沙箱诊断方法论（Windows 环境）

| 铁律 | 说明 |
|---|---|
| **跨调用进程会被回收** | 工具调用里拉起的进程，调用结束后几分钟被清掉。要在调用间隔做 HTTP 验证，必须"同一次调用内"起进程 + 发请求（或改用长驻后台任务） |
| **代理 vs 直连对比** | 怀疑代理 bug 时，同时抓代理地址与直连地址，一致 = 媒体服务器问题，不一致 = 代理问题 |
| **PowerShell `>` 落盘是 UTF-16** | 读诊断文件先按 UTF-16 解码；或脚本内用 `cmd /c "... > file 2>&1"` 让 cmd 内部重定向 |
| **npm / 注册表工具被沙箱拦** | `npm install`、`vcvarsall.bat`（内部调 reg.exe）可能被黑名单挡；验证前端构建可手动解包 tarball 到依赖目录，或关沙箱跑 |
| **真实退出码** | PowerShell 把原生 stderr 当错误 → 报 exit 1（假象）。判脚本真实退出码要在同一次调用里读 `$LASTEXITCODE` |

## 服务端验收清单

1. 全量构建全绿（前端 dist + 服务端 exe + 推流端 exe 都在）。
2. 一键启动（无交互）→ 健康检查接口返回 ok。
3. 摄像头列表接口能看到目标流且状态 online。
4. 浏览器 WebRTC 出画（桌面 + 手机）。
5. **HLS 兜底**：WebRTC 超时或手动切 HLS，两端均出画。
6. 联调验收脚本 pass 计数达标、fail 为 0。
   - 注意：合成 SDP 的 WHEP 探测可能返回 502（缺 ice-ufrag 的**脚本假象**），真浏览器 WebRTC 已验证可用时该条可忽略。
