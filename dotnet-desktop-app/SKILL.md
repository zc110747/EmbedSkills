---
name: dotnet-desktop-app
description: .NET 桌面（WinForms/WPF）：自绘控件 DPI 与裁剪、无音频设备、同一 exe 兼作 CLI、离屏 PNG 验图、实时曲线不重建可视化树。
agent_created: true
---

# .NET 桌面应用（WinForms / WPF）

交付「自带现代 Web 观感」的桌面工具时反复踩到的点：自绘控件的 DPI 与裁剪、
播放器生命周期、同一个 exe 兼作命令行、无消息泵环境下的离屏验图、
以及模型步进快于 UI 时的刷新纪律。只写换项目仍成立的判据。

## 何时用

- 用 WinForms 搭自绘 UI，**编译通过但界面被裁、内容压住副标题、圆角有白边**。
- 用 WPF/MVVM 可视化一个步进快于 UI 的模型（实时曲线、遥测看板）。
- 用 NAudio 播放，出现 `MmException`、进度不动、播放结束事件乱触发。
- 需要在 CI/沙箱（无交互桌面）里产出一张能证明界面真的渲染了的图。

## 通用判据（两种框架都成立）

| 判据 | 结论 |
|---|---|
| 界面缺陷的观测手段 | 布局裁切/遮挡**只有渲染出来才看得见**，读代码发现不了 ⇒ 把"渲染成 PNG + 断言关键文本/计数"做成用例 |
| 设备缺失 | 「没有音频设备 / 没有真模型 / 没有交互桌面」是**合法环境**：要么条件跳过并写明原因，要么明确失败，**不许假通过** |
| 第三方库 API | 一律以**实测成员**为准，不凭记忆写。大版本升级常改名（见 NAudio 2.x→3.x） |
| 同一个 exe 兼作 CLI | 保留 `WinExe` + `AttachConsole(父进程)`；**`AttachConsole` 必须在读 `Console.IsOutputRedirected` 之前**——未附着时该检查会把控制台句柄误判成"已重定向"，于是跳过附着 ⇒ 真实 cmd 窗口静默无输出，而管道环境全绿 |
| 提示符不等待 | `WinExe` 从交互提示符启动时 cmd 不等它；**在批处理里调用 GUI 程序则 cmd 会等** ⇒ 用 `.cmd` 包装器解决等待与退出码透传 |
| 无消息泵 | 离屏/无交互桌面时 `DispatcherTimer` 不 tick、`Loaded` 可能不触发 ⇒ 必须给控件留一个**同步入口**跑同一套渲染路径 |
| 构建验收 | Debug + Release 双构、0 警告；核心逻辑单测不依赖 UI |

## WinForms 判据

| 主题 | 结论 |
|---|---|
| 解决方案格式 | .NET 10 的 `dotnet new sln` 默认产出 **`.slnx`**；要传统 `.sln` 必须 `--format sln` |
| 工程根探测 | 测试/脚本常"向上找 `.sln`" ⇒ 生成 `.slnx` 时**整批用例失败**；探测必须同时接受两者 |
| 自绘圆角 | 别指望 `Region` 直接做圆角：`GraphicsPath` 画圆角后再 `Region(bounds).Exclude(rounded)` **把背景色补进四个角缝** |
| 裁剪 | `Graphics.SetClip` 只吃 `GraphicsPath`（不吃 `Rectangle`）；圆角进度条按路径裁剪，否则直角色块溢出圆角 |
| 文本 | 一律 `TextRenderer.DrawText/MeasureText`（配 `TextFormatFlags.NoPadding \| SingleLine`）；`Graphics.DrawString` 度量与基线不同，混用必然对不齐 |
| 布局 | `TableLayoutPanel`/`FlowLayoutPanel`，**不写绝对坐标**；行高按"内容 + 内边距"显式给，别靠 `AutoSize` 猜 |
| DPI | 缩放系数从 `control.DeviceDpi / 96.0` 现算（`<= 0` 回落 96），所有常量走同一个 `Scale()` |
| 头部遮挡 | 标题/副标题占位必须计入子容器的 **`Padding`**；漏掉会让内容压住副标题，且只在容器变小时才显形 |
| 自定义属性 | 必须标 `[DefaultValue]` 才过设计器序列化分析器，否则报 **WFO1000**（默认按错误处理） |
| 音量 | 设备**未打开**时设 `Volume` 会抛 `MmException("BadDeviceId")` ⇒ 只在 `Init` 之后设，并 try 兜住 |
| 无音频设备 | `DeviceCount == 0` 时加载文件/读时长仍应可用，只有 `Play()` 失败，且包成自己的异常类型，别让裸 `MmException` 冒到 UI |
| 播放事件 | `PlaybackStopped` 在播放器生命周期内**只订阅一次**；用 `_stopRequested` 区分手动 Stop 与自然播完，否则结束事件误触发 |
| 释放顺序 | 先停设备（并等回调跑完）**再** dispose 流，否则播放线程碰到已释放的流 |
| 跨线程 | 播放事件跑在音频线程 ⇒ 一律 `Control.Invoke` 回 UI 线程再改控件 |

## WPF 判据（MVVM 实时可视化）

| 主题 | 结论 |
|---|---|
| 分层 | Core（无 UI、SI 单位）→ ViewModel（持引擎、后台步进）→ View（只绑定）。View **不做计算** |
| 固定步长 | 用**累加器保留余数**：`_last += steps * TimeStep`。⚠️ 写成 `_last = now` 会**丢弃不足一步的余数**，循环一旦快于一步（停止忙等后必然如此），余数永远攒不满 ⇒ 仿真时钟爬行/看起来冻结（曲线只在右缘一条竖线，因为所有样本共用同一时间戳） |
| 停滞处理 | 落后过多时**有界突发 + 重同步**（`steps` 钳到上限后 `_last = now`），否则一次卡顿要追几千步 |
| 暂停 | 每轮空转都把配速时钟**钉在当前 stopwatch 读数**，否则恢复时快进 |
| 一致性 | 每帧**所有**显示值从**同一个快照**读；混入对控制器对象的实时读会产生互相矛盾的撕裂值 |
| 刷新 | UI 定时器只做「快照 → 显示属性」，不驱动物理；`SetField` 值不变不发通知 |
| 自绘曲线 | **不要每帧 `Children.Clear()` 重建视觉树**（多图时每帧上千对象 + 全量布局，FPS 掉到个位数）⇒ 网格层只在尺寸变化时重建，`Polyline.Points` 原地更新，标签只改 `Text`，`PropertyInfo` 缓存，缓冲长度设上限 |
| 引擎重置 | 样本时间戳回退（`t < lastT`）即视为重置，清空缓冲 |
| 小数输入框 | `MultiBinding` + `IMultiValueConverter` 绑 `(value, decimals)`，每框各自精度；`ConvertBack` 返回 `[parsed, Binding.DoNothing]` |
| 暗色 ComboBox | 内置模板用**硬编码浅色系统画刷**且不认 `Background`/`Foreground` ⇒ 白底近白字不可读。必须整套 `ControlTemplate`（ToggleButton 模板 + `SelectionBoxItem` 的 ContentPresenter + Popup + 列表 `IsHighlighted`/`IsSelected` 触发器） |
| 主题字典 | 放独立 `ResourceDictionary` 并用 `MergedDictionaries` 引入，便于**非 UI 宿主**加载同一份；旧内联样式与新字典并存会触发重复键冲突 |
| 离屏渲染 | **从未 `Show()` 的 Window 渲染出来是空白**（顶层视觉没有呈现源）⇒ 把 `window.Content` 摘出来放进 `Border` 宿主，`Measure/Arrange/UpdateLayout` 后 `RenderTargetBitmap.Render(host)` |
| 宿主尺寸 | 宿主按内容全高，否则 `ScrollViewer` 只渲染视口；背景色要带到宿主上（裸内容网格是透明的） |
| 无 `Application` | 控制台 exe 托管 WPF 时 app 级字典/隐式样式不生效 ⇒ `{StaticResource}` 抛 `XamlParseException`。需 `new My.App()`（全限定，避免与命名空间同名冲突）并按 **pack URI 显式加载**主题字典 |
| 命名作用域 | `x:Name` 属于 Window ⇒ `window.FindName(...)` 必须在摘出 Content **之前**解析，重挂到别的父级后 `root.FindName` 会失败 |

## 反模式

- **凭记忆写第三方库 API**：升级后编译报"找不到成员"，凭印象改只会越改越偏。先列真实成员再动手。
- **用 `Assert.Skip` 做跳过**：xUnit 2.x **没有** `Assert.Skip`，且 `SkipException` 构造函数非 public ⇒ 只能"运行期条件 `FactAttribute` 子类"。
- **把 `AutoSize` 当布局算法**：自绘控件 + `AutoSize` 常算出 0 高度，表现为"控件不见了"。
- **用文件大小推音频时长**：编码/头部不确定，必须解码器读。
- **给命令行包装器加自动 `pause`**：`for` 循环与管道会在第一次失败时永久挂住；`pause` 只留给双击用的启动器。
- **用"我这边没抓到输出"推断"程序没输出"**：`.cmd` 介入后 stdout 归属会变，先打 `attach / redirected / streamNull` 探针看事实。
- **让 UI 定时器驱动物理**，或**每帧重建可视化树**。

## 详细资料

- `references/custom-control-painting.md` — 圆角/裁剪/DPI/`TextRenderer`/`DefaultValue` 的落地写法与"界面被裁"排查顺序。
- `references/naudio-playback.md` — NAudio 2.x→3.x 迁移对照、播放器骨架、无设备路径、事件与释放顺序。
- `references/external-cli-integration.md` — 安全调用外部 CLI：`ArgumentList`、双管道防死锁、超时、杀进程树、产物原子落地。
- `references/gui-exe-as-cli.md` — 同一 exe 兼作命令行：子系统取舍、`AttachConsole` 顺序陷阱与探针取证法、退出码契约。
- `references/xunit-conditional-tests.md` — 条件 `Fact` 属性模板、测试工程引用 WinForms 的注意事项、发布命令。
- `references/wpf-realtime-dashboard.md` — 固定步长配速器、自绘曲线、暗色 ComboBox 模板、离屏 PNG 与无 `Application` 宿主的完整代码。

## 验收链

`dotnet build -c Debug` 与 `-c Release` 双构 0 警告 → 核心层单测（断言物理趋势，不只"能跑"）
→ 离屏 PNG 断言关键文本与图表非空 → 需要真设备/真桌面的用例条件跳过并打印原因。
判据最好**独立于被测实现**（用解析解或外部参考对齐），否则是自证。
