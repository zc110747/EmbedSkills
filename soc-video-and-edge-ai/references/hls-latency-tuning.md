# 四·A HLS 时延优化（症状：用户报 5-6s 卡顿、WebRTC 无感）

**分解**：HLS 端到端 ≈ 发布端滞后（服务端分段/排队，实测中位 ~0.75s，含 ≤1 段边界等待）+ **hls.js
frontier gap** = 播放头刻意落后播放列表边缘的段数 × 段长（hls.js 默认 `liveSyncDurationCount:3`）。

**关键物理约束**：MediaMTX mpegts 只能在**关键帧**处起新段 → 段长被上游 GOP 钳制（GOP 1s⇒1s 段、
GOP 4s⇒4s 段）。**降 HLS 时延第一步是推流端 GOP≈1s**（`-g fps -keyint_min fps`，camera-agent `--auto`
已内置 keyint=fps 修正）。

**实测数据**（`scripts/hls_latency_probe.js A|B|C`：chromium + 同源注入 hls.js，读 level details 的
last fragment edge − currentTime；A=默认 sync3，B=sync2+1.5x，C=sync1+2x）：

| frontier gap | @1s GOP | @4s GOP |
|---|---|---|
| A 默认（sync3） | ~2.4s | **~10.4s** |
| B（sync2） | ~1.4s | – |
| C（sync1+2x，零 stall） | ~0.5-1.0s | ~2.4s |

**落地**（player.ts startHLS，bundle index-Ct3uBpII.js）：`liveSyncDurationCount:1,
liveMaxLatencyDurationCount:6, maxLiveSyncPlaybackRate:2, maxBufferLength:8` + 保留容错重试。
真实 App 验证：出画 + 发布端滞后中位 0.75s（媒体播放列表 `#EXT-X-PROGRAM-DATE-TIME` 对时）；
用户端预期 5-6s → ~2.5-3.5s。iOS 原生播放器无这些旋钮，缓冲更大属预期。

**测量要点**：headless 播放器必须 `muted+playsInline`；逐样本用 `page.evaluate` 快读 + `Promise.race`
超时，勿让单个长 evaluate 悬挂；同源页注入 hls.js（`about:blank` 会被 PNA CORS 拦，见上）。
