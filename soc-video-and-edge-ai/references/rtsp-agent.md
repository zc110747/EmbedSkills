# RTSP 推流端（Publisher）实现细节

推流端是**运行在主机上的摄像头采集程序**，同时充当**嵌入式 SoC 板卡的采集仿真器**与真机模板。只换采集源即可上真机。

## 职责边界

| 负责 | 不负责 |
|---|---|
| 摄像头采集 · H264 编码 · RTSP 推送 · 设备状态 · 自动重连 · 配置管理 | RTSP Server · Web Server · Web UI · WebRTC · 数据库 · 用户管理 · 视频转发 |

它是 RTSP Publisher，不是 RTSP Server。真机只换采集源，不碰服务端。

## 可插拔后端

`CameraManager` / `VideoPipeline` / `RtspPublisher` 都是抽象基类，由 `create()` 工厂按编译期宏选实现；开关取值 `auto | gstreamer | sim`，`auto` 探测到 GStreamer 时选 `gstreamer`，否则 `sim`。

| 后端 | 用途 | 依赖 |
|---|---|---|
| `sim` | 无摄像头/无 GStreamer 下跑通状态机、重连、统计、单测（默认 CI） | C++ 标准库 + 日志库 |
| `gstreamer` | 真实采集：平台原生源（如 mfvideosrc/dshowvideosrc/ksvideosrc）→ H264 → rtspclientsink | GStreamer 1.0（MSVC） |
| `v4l2`（真机） | 只替换采集实现，**保持 H264/RTSP Push/Stream ID 接口不变** | V4L2 + 硬件编码（MPP/GStreamer） |

三条铁律：采集层独立封装；业务代码不散落平台 API；接口稳定以便真机替换。

### 接口契约（每个头只放纯虚函数与数据结构）

```cpp
// 采集层隔离点
class CameraManager {
public:
    static std::unique_ptr<CameraManager> create();
    virtual std::vector<CameraInfo> enumerate() = 0;   // id/name/resolutions/fps
    virtual bool is_available(int id) const = 0;
    virtual std::string backend_name() const = 0;
};

// 整条图：采集→转换→编码→parse→rtp→rtspclientsink
class VideoPipeline {
public:
    static std::unique_ptr<VideoPipeline> create();
    virtual bool build(const PipelineParams&, const std::string& rtsp_url) = 0;
    virtual bool start() = 0;
    virtual void stop() = 0;
    virtual Statistics   get_stats() const = 0;
    virtual StreamStatus get_status() const = 0;
    virtual void set_status_callback(std::function<void(StreamStatus)>) = 0;
    virtual bool check_plugins(std::vector<std::string>* missing = nullptr) = 0; // 缺插件给明确错误，绝不崩
    virtual void simulate_link_lost() {}   // SIM 专用：制造断链以验重连
};

// 只拼 URL + 连接/断开判定（整条图在 pipeline 里）
class RtspPublisher {
public:
    static std::unique_ptr<RtspPublisher> create();
    virtual std::string build_url(const RtspLocation&) const = 0;
    virtual bool connect(const std::string& url) = 0;
    virtual void disconnect() = 0;
    virtual bool is_connected() const = 0;
};
```

每个后端各自实现三个 `create()`，在 `.cpp` 末尾 `return std::make_unique<...>();`。

### 目录与构建切分

```
<根>/include/<pkg>/   types.h config.h camera_manager.h video_pipeline.h
                      rtsp_publisher.h stream_controller.h backoff.h logger.h
<根>/src/
  main.cpp                  CLI 解析 + 优先级 + SIGINT 优雅退出
  camera/                   camera_manager_sim.cpp / camera_manager_gst.cpp
  pipeline/                 video_pipeline_sim.cpp / video_pipeline_gst.cpp
  rtsp/                     rtsp_publisher_sim.cpp / rtsp_publisher_gst.cpp
  config/config.cpp         极简配置解析（无第三方依赖）
  common/stream_controller.cpp  编排 + 自动重连
<根>/tests/                 零依赖单测 + 用例，强制 SIM 后端
<根>/scripts/               构建脚本 / e2e 脚本
<根>/config/*.yaml          运行配置
<根>/<media-server>.yml     端到端验收用 RTSP 服务器配置
```

CMake 按后端切源文件：

```cmake
if(BACKEND STREQUAL "gstreamer")
  list(APPEND SOURCES camera/camera_manager_gst.cpp pipeline/video_pipeline_gst.cpp rtsp/rtsp_publisher_gst.cpp)
else()
  list(APPEND SOURCES camera/camera_manager_sim.cpp pipeline/video_pipeline_sim.cpp rtsp/rtsp_publisher_sim.cpp)
endif()
```

## 状态机与统计

```cpp
enum class StreamStatus { DISCONNECTED, CONNECTING, CONNECTED, STREAMING, ERROR };
enum class CameraStatus { CLOSED, OPENING, OPEN, ERROR };
struct Statistics { uint64_t frames=0; uint64_t dropped=0; double bitrate_kbps=0.0; };
struct DeviceInfo { std::string device_id, device_name, firmware_version;
                    CameraStatus camera_status; StreamStatus stream_status;
                    int width,height,fps,bitrate_kbps; };   // 预留真机同款状态接口
```

状态变化统一经 `set_status_callback` 广播；`STREAMING/DISCONNECTED/ERROR` 全程有 INFO/WARN/ERROR 日志。

## 断线退避重连

后台线程轮询状态：一旦 `DISCONNECTED` 且仍应运行，按退避调度 sleep 后重启（stop→build→connect→start）。

```cpp
class BackoffScheduler {
    explicit BackoffScheduler(std::vector<int> schedule = {1,2,5,10});
    int  next();    // 越界返回最后一个元素（封顶，不无限增长）
    void reset();
};
```

**稳定宽限（`kStableGraceSec = 3.0`）**：rtspclientsink 异步建连，管线翻到 PLAYING 时握手可能还没完成，会出现"假 STREAMING"。因此只有 STREAMING **稳定保持 ≥3s** 才把尝试计数归零并 `reset()` 退避；否则一段假 STREAMING 就会把正在升级的 1/2/5/10s 清零。

优雅退出（Ctrl+C）：停止采集 → 停止编码 → 停止 RTSP → 释放 GStreamer → 释放摄像头 → 退出。绝不因普通网络错误崩溃退出。

## 配置

自写**无依赖**配置子集解析（嵌套 map + scalar，处理注释/引号/缩进栈），避免引 yaml-cpp 之类库。
优先级：**CLI 参数 > 配置文件 > 内置默认**。

```yaml
camera:  { id:0, width:1280, height:720, fps:30 }   # auto:true 走原生协商
encoder: { codec:h264, bitrate:4000, keyframe_interval:30 }
stream:  { id:<stream-id> }
rtsp:    { server:<host>, port:<rtsp-port> }
device_id: <device-id>
log_level: info
```

## 日志

日志层只薄封装一个后端库，业务只调 `LOG_TRACE/DEBUG/INFO/WARN/ERROR` 宏，便于将来替换。级别支持 trace/debug/info/warn/error；MSVC 编译加 `/utf-8`，否则中文报 C4819。

## 零依赖单测（SIM 后端，可无头）

用注册表宏搭最简框架，不引 gtest：

```cpp
#define TEST(name) \
  static bool name##_impl(); \
  static ::test::Registrar name##_reg(#name, name##_impl); \
  static bool name##_impl()
#define ASSERT(cond) ...      // 失败打 __FILE__:__LINE__ 并返回 false
#define ASSERT_EQ(a,b) ...
```

测试 target **强制 SIM 后端**，复用 app 的 `*_sim.cpp` + `stream_controller.cpp` + `config.cpp`。覆盖：摄像头枚举、管线创建、编码、RTSP 连接/断开、自动重连、参数错误、正常退出（含退避封顶）。

- 重连单测把退避调度改成全 0，避免长等；用 `simulate_link_lost()` 触发断链验自动恢复。
- 跑法：`ctest --test-dir <build-dir> --output-on-failure`

## 端到端验收（真 GStreamer 后端）

媒体服务器配置关键项：

```yaml
paths:
  all_others:            # 允许推任意 RTSP 路径，否则报 path '<stream-id>' is not configured
    rtspTransport: tcp   # 与 rtspclientsink 一致，避免 UDP 乱序
    record: no           # 不落盘，不引入缓冲
```

播放端低延迟旗标（**`-rtsp_flags nobuffer` 是错的**，ffplay 会 `Invalid argument` 直接退出、窗口永不出现）：

```
ffplay -rtsp_transport tcp -fflags nobuffer -flags low_delay \
       -probesize 32768 -analyzeduration 0 -framedrop rtsp://<host>:<rtsp-port>/<stream-id>
```

验收三步：
1. 起媒体服务器 → 推流端 `--camera 0 --stream <stream-id> --auto` → 播放端看到实时画面。
2. 杀媒体服务器：推流端**不退出**，状态 DISCONNECTED 并按 1/2/5/10s 退避。
3. 重启媒体服务器：推流端**自动恢复** STREAMING。

**判定回放的坑**：自动恢复以**媒体服务器日志**（逐行实时刷盘）里的"stream is available and online"为准；不要读推流端日志（stdout 被缓冲，且受稳定宽限延迟）。外部工具走 PATH 裸名，不写绝对路径；自产 exe 用相对路径。

## 故障定位最短路径

```
整条链不工作
 ├─ 1. 清残留进程（媒体服务器 / 推流端 / 播放器）  ← 最常见
 ├─ 2. 读脚本预检输出，看有没有 [FAIL]
 ├─ 3. 读推流端日志 → "Failed to set pipeline to PLAYING"？
 │                        ├─ 设备序号不存在（只有 0 却配了 1）→ 用 --list 核对
 │                        └─ caps 协商失败（强制分辨率摄像头产不出）→ 加 --auto
 ├─ 4. 读媒体服务器日志 → "no stream is available" 说明上游没推上来，回第 3 步
 └─ 5. 播放器窗口不出现 → 多半是 -rtsp_flags nobuffer 参数非法
```

日志可信度：媒体服务器日志（实时刷盘，最可信）> 推流端日志（stdout 有缓冲）> 脚本控制台（最不可信，常被环境吞掉）。

## 开发节奏

严格按阶段推进，**禁止在无法编译时堆积代码**：环境检查 → 摄像头枚举 → 采集 → 编码 → RTSP 推送 → 自动重连 → 参数配置 → 完整测试。每阶段：改 → 编译 → 测试 → 修复 → 进下一阶段。
