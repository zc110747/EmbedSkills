---
name: visual-verification
description: 看不到界面时怎么验：Windows GUI 截图与点击（BitBlt、DPI）、无浏览器前端取证（esbuild、SSR）、WebGL 首帧与像素断言。
agent_created: true
---

# 无界面视觉验收（Web 前端 / Windows GUI）

界面类问题的共同前提：**没有可断言的控件树，也没有「人眼确认」这一步**。
两个战场技术栈不同，方法论同构 —— 抓图 → 量化判据 → 单次调用内编排 → 先查环境。

| 战场 | 观测手段 | 典型请求 |
|---|---|---|
| **Web 前端** | esbuild 打包客户端模块打活服务、`react-dom/server` 渲染、逐帧记录器、`getImageData` 量像素跨度 | 「仪表盘写完没人打开过」「页面显示 `undefined` 却不报错」「截图抓不到首帧重影」 |
| **Windows GUI** | ctypes + BitBlt 抓客户区、DPI 感知 `mouse_event` 点击、纯 Python PNG 裁剪放大 | 「GUI 截图」「自动化验收」「点击没反应」「DPI 缩放后偏了」 |

## 何时用

- 沙箱封掉 Chromium/Playwright，却要证明前端**对着活后端真的能跑**。
- 自绘 GUI（SDL / LVGL / Qt）需要截图验收，因为**没有控件树**。
- 故障形态是「编译通过、单测全绿、屏幕上就是 `undefined` / 全黑 / 错位」。
- 「首帧重影、一交互就消失、截图永远抓不到」这类瞬态问题。
- 手上没有 Pillow / numpy / pyautogui，或合成点击没反应、截图拍到 IDE。

## 通用四条

1. **编译通过 ≠ 运行时正确**：「不抛异常」不是判据，**字段存在性 / 像素事实**才是。
   自绘界面里「日志正常 + 界面全错」是常态。
2. **先试真浏览器/真窗口，再下沉**：本机已装的 Edge/Chrome 比下载 Chromium 快得多；
   退出码非 0 + 输出 0 字节 + stderr 空 ⇒ 环境层拦截，别再调参数，转 Node 侧方案。
3. **一条命令内跑完**：上一次调用里 `(cmd &)` 起的后台进程，**下次调用就没了**。
   必须 `taskkill` 清残留 → 启动 → 等足（SDL/LVGL 初始化 12 s 起）→ 点 → 截，串在同一次调用里。
4. **坐标/端口/地址只认物理与单一真值源**：算点击坐标只看物理像素，别看「展示给你看的缩放图」
   （按缩放图算会偏 75 px）；端口与白名单、探测地址、绑定地址读同一个变量。

## Web 前端要点

- **分层判定**：客户端模块（L1）与组件渲染（L2）可在 Node 里全额覆盖；
  时序相关的 effects/轮询（L3）与 socket/CORS/打包产物（L4）必须真浏览器。
  交付说明**写明哪层没覆盖**，别用一个绿勾假装全测过。
- **Check A**：用 esbuild 打包**客户端自己的模块**（不重写调用逻辑）去打活服务；
  逐个 URL 实打，每个面板字段的存在性**单独断言**，`=== undefined` 才算失败。
- **Check B**：`renderToStaticMarkup` 只要 DOM 树、不要 DOM；产物不得含
  `undefined`/`NaN`/`[object Object]`，且**必须有正样本断言**（否则空产物也过关）。
- payload **必须从活服务现取**；手写 fixture 测的是「我以为的形状」。
- 空态（未连接 session）必须单独渲染一遍，白屏的唯一解读是「前端坏了」。
- **CORS 不能靠读配置**：写死的白名单读起来永远正常，而每个请求被 400 拒、浏览器报成
  「网络错误」。Node 侧请求结构上看不见它 —— 全绿与浏览器全挂可以同时为真。
  改用**活服务两侧预检**（配过的 origin → 200，没配过的 → 400），回归断言也要**两侧**。
- **首帧分流**：「首帧多出一份、一动就正常」是三码事（画两次且变换不同 /
  画两次且变换相同 / 单帧陈旧变换），先定类再取证，三类证据与修法完全不同。
- 逐帧记录器读**渲染真用的矩阵**，不调 `updateMatrixWorld()`；帧 0 读到单位阵常是仪器伪影。
- 抓不到瞬态不要靠多截图，要**每一帧**留证；两张截图先平移对齐再取残差，看残差**空间分布**。
- 比对前**先打印图像尺寸**：按缩略图尺寸裁会裁到空白、残差假性为 0。
- Canvas 2D 的「确实更可见」要可复核：`getImageData` 量目标色曲线的纵向 `span`，
  判据用 `span/h` 比例；对比前先滑出环形缓冲历史。

## Windows GUI 要点

- **只抓客户区**：`GetClientRect` + `ClientToScreen`，别连标题栏，否则按 UI 坐标点的偏移
  差一个标题栏高度。`biHeight` 取**负**得自上而下行序，省一次翻转。
- 抓之前必须 `ShowWindow(SW_RESTORE)` + `SetForegroundWindow` + `BringWindowToTop`
  —— 少这一步，「截图抓到 IDE / 黑屏」是最常见结果（BitBlt 读的是合成后的桌面，被遮挡就拍到上层窗口）。
- **DPI**：缩放 150% 时逻辑 800×480 的客户区是 1200×720 物理像素，`SetCursorPos` 收物理像素。
  先 `SetProcessDpiAwarenessContext(-4)`，再**从客户区宽度反推 scale**，不要写死。
- **用真实输入，不要 `PostMessage`**：SDL2 会忽略它没看到到达鼠标焦点的投递消息。
  `mouse_event` 是合成输入，**用户会看到鼠标真的动**，务必提前告知。
- 合成点击**可能触发额外导航**（整条页头可点），截详情页要在点击后立刻截。
- 没有 Pillow 也能读 PNG（`struct` + `zlib`，filter 0–4），放大 4~8 倍才能判断
  「字符是不是被右边缘裁掉了」；程序输出的 24bpp BMP 需转 PNG 才能被看图工具显示。

## 合格交付长什么样

| 项 | 证据 |
|---|---|
| 进程真的起来了 | 启动日志关键行（后端就绪、监听端口、进入主循环） |
| 界面渲染正确 | 主界面截图 + 目标区域**放大图** |
| 交互链路通 | 点击后的事件日志 |
| 异步结果落地 | 请求耗时与返回长度日志 + 落地后截图 |
| 没有退化 | 长跑若干秒后有意义告警计数为 0 |

## 详细资料

- `references/win-gui-capture.md` —— Windows GUI 完整配方：BitBlt 代码、DPI 反推、PNG 编解码、编排脚本
- `references/esbuild-probe.md` —— Check A：打包客户端模块打活服务、字段存在性断言
- `references/ssr-render-probe.md` —— Check B：组件 SSR 渲染、red flag 扫描、正样本与空态
- `references/webgl-frame-recorder.md` —— 首帧三类分流、逐帧记录器三条纪律、截图残差
- `references/canvas-pixel-assert.md` —— Canvas 2D 像素跨度取证与环形缓冲污染
- `references/env-traps.md` —— 浏览器可用性判定、CORS 两端预检、后台进程与 shell 坑
