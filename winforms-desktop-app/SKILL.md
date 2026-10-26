---
name: winforms-desktop-app
description: C#/.NET WinForms：自绘圆角控件的 DPI 与裁剪、NAudio 3.x 播放器生命周期与无音频设备、同一 exe 兼作 CLI、WFO1000 与 DefaultValue。
agent_created: true
---

# WinForms 桌面应用（.NET / C#）

用 C#/.NET 交付**自带现代 Web 观感**（浅色页底 + 白色圆角卡片 + 统一色板）的桌面工具时
反复踩到的点：工具链契约、自绘控件的 DPI 与裁剪、音频播放器生命周期、外部 CLI 集成、
以及"哪些测试必须条件跳过"。只保留换项目仍成立的判据。

## 何时用

- 用 WinForms（或任何 `System.Windows.Forms` 宿主）搭一个自绘 UI 的小工具。
- 编译通过但**界面被裁、内容压住副标题、圆角出现白边/锯齿**。
- 用 NAudio 播放音频，出现 `MmException`、进度条不动、播放结束事件乱触发。
- 需要"诚实"的验收：部分用例依赖真设备 / 大二进制模型 / 交互桌面，不能假装通过。

## 核心知识点

| 知识点 | 结论 |
|---|---|
| 解决方案格式 | .NET 10 的 `dotnet new sln` 默认产出 **`.slnx`**；要传统 `.sln` 必须 `--format sln` |
| 找工程根 | 测试/脚本常按"向上找 `.sln`"定位工程根 ⇒ 生成的是 `.slnx` 时**整批用例失败**；探测要同时接受两者 |
| 库 API 以实测为准 | NAudio 3.x 相对 2.x **改了名**：`WaveOutEvent`→`WaveOut`、`DesiredLatency`→`BufferMilliseconds`、`GetPositionTimeSpan()` 变成 `NAudio.Utils` 的扩展方法。**不要凭记忆写 API**，先列真实成员 |
| 自定义控件属性 | 属性要标 `[DefaultValue]` 才过 WinForms 设计器序列化分析器，否则报 **WFO1000**（"property not configured for code serialization"，默认按错误处理） |
| 圆角 | 别指望 `Region` 直接做圆角：用 `GraphicsPath` 画圆角，再用 `Region(bounds).Exclude(rounded)` **把页面底色补进四个角缝** |
| 裁剪 | `Graphics.SetClip` 只吃 `GraphicsPath`（不给 `Rectangle`）；圆角进度条必须按路径裁剪，否则直角色块溢出圆角 |
| 文本 | 一律 `TextRenderer.DrawText/MeasureText`（配 `TextFormatFlags.NoPadding \| SingleLine`），**不要** `Graphics.DrawString` —— 两者度量与基线不同，混用必然对不齐 |
| 布局 | 用 `TableLayoutPanel`/`FlowLayoutPanel`，**不写绝对坐标**；行高按"内容 + 内边距"显式给，别靠 `AutoSize` 猜 |
| DPI | 缩放系数从 `control.DeviceDpi / 96.0` 现算（`DeviceDpi <= 0` 回落 96），**所有常量走同一个 `Scale()`** |
| 头部遮挡 | 卡片的标题/副标题占位必须计入子容器的 **`Padding`**（含 header 顶部偏移）—— 漏掉会让内容压住副标题，且只在容器高度变小时才显形 |
| 音量 | 设备**未打开**时设 `WaveOut.Volume` 会抛 `MmException("BadDeviceId calling waveOutSetVolume")` ⇒ 音量只能在 `Init` 之后设，且要 try 兜住 |
| 无音频设备 | `WaveOut.DeviceCount == 0` 是**合法环境**：加载文件/读时长仍应可用，只有 `Play()` 失败 —— 且必须包成自己的异常类型，别让裸 `MmException` 冒到 UI |
| 事件只订阅一次 | `PlaybackStopped` 在播放器生命周期内**只订阅一次**；用 `_stopRequested` 区分"手动 Stop"与"自然播完"，否则 `PlaybackEnded` 会误触发 |
| 释放顺序 | 先停设备（并等回调跑完）**再** dispose 播放流，否则播放线程会碰到已释放的流 |
| 跨线程回 UI | 播放事件跑在音频线程上 ⇒ 一律经 `Control.Invoke` 回 UI 线程再改控件 |
| 同一个 exe 兼作 CLI | 保留 `WinExe` + `AttachConsole(父进程)`；**`AttachConsole` 必须在读 `Console.IsOutputRedirected` 之前调用** —— 未附着时该检查会把控制台句柄误判成"已重定向"，于是"跳过附着"⇒ 真实 cmd 窗口静默无输出，而管道环境测试全绿 |
| 提示符不等待 | WinExe 从 cmd 交互提示符启动时 cmd **不等**它；**在批处理里调用 GUI 程序则 cmd 会等** ⇒ 用一个 `.cmd` 包装器解决等待与退出码透传 |

## 反模式

- **凭记忆写第三方库 API**：升级/改版后编译报"找不到成员"，凭印象改只会越改越偏。
  先列真实成员（反射小工具，或让编译器给出候选），再动手。
- **用 `Assert.Skip` 做跳过**：xUnit 2.x **没有** `Assert.Skip`/`Assert.SkipWhen`，
  且 `SkipException` 的构造函数不是 public ⇒ 只能用"运行期条件 `FactAttribute` 子类"。
- **把 `AutoSize` 当布局算法**：自绘控件 + `AutoSize` 常算出 0 高度，表现为"控件不见了"。
- **用文件大小推音频时长**：编码/头部不确定，必须用解码器读（`WaveFileReader.TotalTime`）。
- **假成功**：设备/模型/桌面不可用时让用例"通过"或吞掉异常 = 把风险留给用户。
  要么条件跳过并写明原因，要么明确失败。
- **界面缺陷靠读代码发现**：自绘布局的裁切/遮挡**只有渲染出来才看得见**。
  把"渲染成 PNG + 断言关键文本/计数"做成用例（见 references）。
- **用"我这边没抓到输出"推断"程序没输出"**：`.cmd` 一旦介入，stdout 的归属就可能变。
  先把 `attach / redirected / streamNull` 打成探针看事实（见 `references/gui-exe-as-cli.md` §3）。
- **给命令行包装器加自动 `pause`**：`for` 循环与管道会在第一次失败时永久挂住。
  `pause` 只留给双击用的启动器。

## 详细资料

- `references/naudio-playback.md` — NAudio 2.x→3.x 迁移对照、播放器骨架、无设备路径、事件与释放顺序。
- `references/custom-control-painting.md` — 圆角/裁剪/DPI/`TextRenderer`/`DefaultValue`(WFO1000) 的落地写法，与"界面被裁"的排查顺序。
- `references/external-cli-integration.md` — 安全调用外部 CLI：`ArgumentList`、双管道防死锁、超时、杀进程树、产物原子落地。
- `references/gui-exe-as-cli.md` — 同一个 exe 兼作命令行：子系统取舍、`AttachConsole` 顺序陷阱与探针取证法、批处理包装器、退出码契约。
- `references/xunit-conditional-tests.md` — 条件 Fact 属性模板（真模型/音频设备/交互桌面）、测试工程引用 WinForms 的注意事项、发布命令。
