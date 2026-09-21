# 端侧 AI 旁路管线（tee + appsink + 零依赖推理）

在**既有视频管线**（采集→编码→RTSP）上叠加一条**完全独立**的 AI 分支。核心命题只有一个：**AI 出现任何异常，视频流必须照常**，其余都是实现细节。

## 绝对约束

| 约束 | 落地手段 |
|---|---|
| 模型加载失败 / 推理异常 / 跟踪异常 / 线程退出 | 全部 try-catch 隔离；初始化返回 false 后视频照常 |
| 不得在编码前同步阻塞 | AI 走独立线程 + 有界队列，绝不在视频回调里推理 |
| 不得重开摄像头 | 用 `tee` 从既有管线分帧，不新建采集源 |
| 队列不得无限增长 | 有界（1~2），满则**丢旧保新** |
| 不得硬编码参数 | 全部进配置层（`ai:` 段 + CLI 覆盖） |

**最硬的一条**：AI 关闭时，`gst_parse_launch` 的描述字符串必须与加 AI 之前**逐字节相同**。做法：把 AI 分支字符串**拼在描述末尾**，用开关决定是否追加 `tee`。
验收办法：分别以"关 AI / 开 AI"运行，抓日志里 `Pipeline:` 那行做 diff。

## 取帧：tee + leaky queue + appsink

```text
... videoconvert name=conv ! tee name=aisplit
aisplit. ! queue name=aiq max-size-buffers=2 max-size-bytes=0 max-size-time=0 leaky=upstream
        ! videoconvert name=aiconv ! video/x-raw,format=RGB
        ! appsink name=aisink max-buffers=1 drop=true sync=false
aisplit. ! <原有编码链路>
```

要点：
- `leaky=upstream` + `appsink drop=true sync=false max-buffers=1`：**AI 慢就丢帧，绝不反压视频**。这是"不影响视频"的物理保证，比任何 try-catch 都重要。
- **appsink 出原始分辨率 RGB，不要在 GStreamer 里缩放到 640**。在 GStreamer 里缩放会改变宽高比，导致 bbox 反变换算错；letterbox 放在 C++ 侧做，才能精确逆变换。
- `videoconvert` 只转像素格式，**不缩放**（别指望它当 videoscale 用）。
- 取 RGB 行**必须按 stride 逐行 memcpy**：`GST_VIDEO_INFO_PLANE_STRIDE(info,0)` 常因 4 字节对齐而大于 `width*3`，整块 memcpy 会得到错位图像（表现为检测框乱飘）。

用回调 API（不是 signal）：

```cpp
GstAppSinkCallbacks cbs{};                              // 零初始化，避免野指针
cbs.new_sample = &GstVideoPipeline::ai_new_sample_cb;   // static
gst_app_sink_set_callbacks(GST_APP_SINK(as), &cbs, this, nullptr);
```

回调里只做：取 caps → `gst_video_info_from_caps` → map → 逐行拷贝 → 投递队列。
**回调内部也必须 try-catch**，异常不能穿回 GStreamer 的 streaming thread。

## frame_id / timestamp 语义（最易做错）

| 字段 | 正确来源 | 错误做法 |
|---|---|---|
| `frame_id` | 视频帧计数器（回调里自增） | 用结果生成序号（AI 5fps 时编号会缺 5/6） |
| `timestamp` | `GST_BUFFER_PTS(buf) / GST_MSECOND` | `time(NULL)`（与视频时间基准脱钩） |

`tee` 把**每一帧**都喂给 appsink，所以 `frame_id` 天然是"摄像头帧号"。30fps 源 + 5fps AI ⇒ 相邻结果的 `frame_id` 间隔应 ≈6，这是自检指标。PTS 无效时退化到 0，不要造假。

## 采样策略（规格 5fps vs 真实低帧率源）

低帧率源（如 8fps）再按 5fps 抽是浪费；低于阈值（默认 10fps）时退化为**来一帧算一帧**：

```cpp
const bool full_rate = (video_fps > 0 && video_fps < cfg.full_rate_below_fps);
interval_ms_ = full_rate ? 0 : (cfg.fps > 0 ? 1000 / cfg.fps : 0);
```

- `interval_ms_ > 0`：节拍等待；若已落后则**重同步** `last_due_ = now + step`，不要补跑（补跑会造成突发堆积）。
- `interval_ms_ == 0`：退化为条件等待，来一帧算一帧。
- 取帧时取**最新**一帧，清空其余并计入 `skipped_`——与其算旧帧，不如算新帧。
- 统计口径：`dropped = 入队丢弃 + skipped`，分开记便于定位。

## 抽象层（为其他推理后端留口）

```text
IDetector          -> YOLODetector (ONNX Runtime) | 其他后端 | NullDetector(无依赖时兜底)
ITracker           -> ByteTrackTracker
IMetadataTransport -> HttpMetadataTransport | WebSocket / MQTT
```

真实现用编译宏包住，`#else` 提供空实现（`backend_name()=="none"`、初始化返回 false）。**没装推理运行时也能零警告编译、视频照跑**，这是可选依赖该有的样子。

## CMake：运行时自动探测 + 构建后拷贝动态库

```cmake
option(ENABLE_AI "" ON)
set(INFER_ROOT "" CACHE PATH "")
# 候选顺序：缓存变量 -> 环境变量 -> 常见安装位置 -> 系统默认前缀
# 只有存在 onnxruntime_cxx_api.h 才接受；find_library 用 NO_DEFAULT_PATH
```

- 必须 **POST_BUILD 把动态库拷到 exe 同目录**，否则双击就崩，且报错信息完全不提缺失的 DLL。
- 测试 target 也要同样处理（它链接了同样的源文件）。
- 依赖路径**不能有空格、不能有中文**；避免系统 Program Files（拷 DLL 可能触发 UAC）。

## 结果上报通道（含 TLS 客户端选择）

- 上报走独立传输抽象，HTTP 起步，后续可换 WebSocket/MQTT；报文按**加法扩展**（新增可选字段，旧消息逐字节不变）。
- **Windows C++ 客户端连 Go `crypto/tls` 服务端不要用 Schannel**：TLS 1.2 首个 app-data 记录的 explicit nonce 出现 off-by-one（用 seqnum 1 而非 0），GCM/CBC 均被 `bad record mac` 拒收；而握手本身成功（双方 Finished 校验通过），极易误判为偶发网络问题。
- 备选方案：客户端 TLS 层换 OpenSSL（`TLS_client_method` + 最低 TLS 1.2），WS 帧/握手/auth 逻辑复用，服务端不动；嵌入式侧用 mbedTLS（同一标准语义）。Windows 上可用免安装的 OpenSSL 便携 ZIP（含 MSVC include/lib）。
- OpenSSL 接入要点：CMake 按 `include/openssl/ssl.h` 探测 → `find_package(OpenSSL REQUIRED)` → 链接 `OpenSSL::SSL OpenSSL::Crypto`；构建后把 `libssl-*`/`libcrypto-*` 拷到 exe 旁。
- 校验三档：insecure = `SSL_VERIFY_NONE`；指定 CA = `SSL_CTX_load_verify_locations` + 主机名校验；默认系统信任库。`SSL_MODE_AUTO_RETRY` 必开。
- **IP 字面量的主机名校验走 `X509_VERIFY_PARAM_set1_ip_asc`**（匹配证书 IP-SAN）；`SSL_set1_host` 只有 DNS 语义，连回环地址会校验失败。
- SNI 用 `SSL_set_tlsext_host_name`；读写用 `SSL_write_ex/SSL_read_ex` 循环；错误统一 `ERR_get_error()` 排队打印（否则错误信息静默丢失）。
- 通用坑：**HTTP/WS 头名解析必须大小写无关**（RFC 7230）。某实现返回首字母大写的头名时，小写查找会假报 "missing Sec-WebSocket-Accept"。潜在 bug 可能在旧实现里从未被执行到——**换传输层时整条路径要重新走一遍端到端**。
