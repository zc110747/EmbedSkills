# 零依赖 YOLO ONNX 解码与 ByteTrack

前提：**只有推理运行时（ONNX Runtime），没有 OpenCV、没有 Eigen**。所有前后处理与跟踪均手写。

## 模型加载

**先把模型文件读进内存，再用内存指针建 Session**（`Ort::Session(env, bytes.data(), bytes.size(), opts)`），绕开 `ORTCHAR_T` 在 Windows 上的宽字符路径坑。顺手设置 `SetIntraOpNumThreads(n)`、`SetLogSeverityLevel(3)`（只报错误）。

模型获取：Ultralytics assets 仓库 release 直接提供**官方 ONNX 成品**（检测 / pose），无需自行导出。

## 输出张量两套布局

用形状判别：`transposed = (d1 < d2)`。

| 形状 | 来源 | 读法 |
|---|---|---|
| `{1, 84, 8400}` | YOLOv8 / YOLO11 原生 | 按 channel 行读 |
| `{1, 8400, 84}` | 多数第三方导出 | 按 anchor 行读 |

YOLO11 检测输出与 YOLOv8 **完全同布局**，换模型路径即用，解码零改动。

## 解码要点

1. **YOLOv8 输出的 objness/cls 分数已经 sigmoid 过，不要再 sigmoid**。重复 sigmoid 会把分数压到 ~0.5 附近，表现为"置信度都很怪"。
2. 前处理 letterbox：等比缩放 + **pad=114**（与 Ultralytics 一致）、双线性插值；HWC→CHW 并 /255。
3. bbox 反变换回**原始视频像素**：`((cx ± w/2) - pad_x) / scale`，再 clamp 到 `[0, width/height]`。
4. NMS 自己写：按类分组、按分数降序、贪心 IoU 抑制（约 40 行，用不上 OpenCV 的 NMSBoxes）。
5. 只保留 `class_id == 0`（person）时，过滤放在 NMS **之前**，省算力。

参考规模：letterbox ~60 行、NMS ~40 行、解码 ~120 行。
桌面 CPU + nano 级模型：640×640 约 **90ms/帧**（≈11fps 上限），够 5fps 采样用。

## 姿态模型（pose）解码

- **判型优先读 ONNX 内嵌 metadata**：`session_->GetModelMetadata().LookupCustomMetadataMapAllocated("kpt_shape", alloc)`（值形如 `"[17, 3]"`）；退化方案用形状启发式 `(C-5) % 3 == 0 且 K >= 4`（C=56→17）。注意纯检测模型可能被启发式误判，**metadata 优先**。
- 通道布局：`4 box + 1 cls + 3*K kpt`。
- **关键点置信度在模型内已 sigmoid**，解码只 clamp 到 [0,1]，**绝不再 sigmoid**（与 cls 分数同一条铁律）。
- kpt 坐标位于输入图像素空间，逆变换与 bbox 相同：`(v - pad) / scale`，再 clamp 进原始帧。
- 把解码抽成**无运行时依赖的纯函数头文件**，例如
  `decode_yolo_output(data, rows, cols, channel_major, ...)`：单测用**合成张量**即可覆盖双布局 + 逆变换 + 置信度透传，不必依赖真模型；真模型回归再用官方示例图（4 人 17 关键点全落帧内）。
- 关键点经跟踪器**原样透传**：`Detection.keypoints → DetBox/STrack.kpts → TrackedObject.keypoints`（跟踪器只吃 bbox，不解释 kpt）。
- 协议做**加法扩展**：objects 增加可选 `"keypoints":[[x,y,conf],…]`（x/y 为原始像素、保留 2 位小数、裁剪入帧），检测模型消息**逐字节不变**；心跳的 ai 段加 `"keypoints":N`。
- 实测（桌面 CPU @640×640）：检测约 88ms/帧，pose 约 112~150ms/帧，5fps 采样均够用。

## 零依赖 ByteTrack（无 Eigen）

状态量用 **8 维** `[cx, cy, w, h, vcx, vcy, vw, vh]`（常速模型），观测 4 维。

- 不要用"固定宽高比 + 高度为主"的 5 维变体：宽度会随高度线性外推，容易**收敛到 w→0** 导致跟踪漂移、框越收越窄直至消失。

矩阵运算自己写模板：`Mat<R,C>` + `mul` / `trans` / `inv<N>`（Gauss-Jordan 带部分选主元，约 80 行）。
匹配用**贪心**替代 lapjv（匈牙利算法）：按代价升序取互斥对，在小目标数（<20）下效果等价，省掉一个依赖。

两级关联：
1. 高分框：`cost = 1 - iou * score`（fuse_score），阈值 `match_threshold`（默认 0.8）
2. 低分框（`>= low_confidence`，默认 0.1）：IoU 阈值 0.5，救回被遮挡目标
3. 未确认（tracked 但未 activate）轨迹：IoU 0.7 再匹配一次

`max_time_lost = frame_rate / 30 * track_buffer` —— 注意**用真实 AI 帧率换算**：低帧率源下若仍按 30 算，目标会过早被销毁（ID 跳变）。

## 踩坑速查

| 现象 | 根因 |
|---|---|
| 检测框乱飘 / 完全乱 | RGB 拷贝没按 stride 逐行，图像错位 |
| 置信度都很怪 | 对已 sigmoid 的输出又做了一次 sigmoid |
| 跟踪框宽度越来越窄直到消失 | 用了 5 维（宽高比固定）卡尔曼，w 随 h 外推到 0 |
| 低帧率源 ID 频繁跳变 | `max_time_lost` 按 30fps 换算，未用真实 AI 帧率 |
| 采样后编号跳号 | frame_id 取自结果序号而非视频帧计数器 |
| AI FPS 上不去 | CPU 推理 nano 级模型约 90ms/帧是物理上限，别指望 30fps；提速靠 GPU/专用加速器后端 |
| 双击 exe 直接崩、无提示 | 推理运行时 DLL 没拷到 exe 同目录 |
| RTSP 连不上、反复重连 | 多半是媒体服务器进程被回收（会话级后台起的会随会话退出），不是管线问题 |
