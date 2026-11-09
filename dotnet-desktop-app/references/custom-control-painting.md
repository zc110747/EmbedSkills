# 自绘控件：圆角、裁剪、DPI、文本与"界面被裁"排查

目标形态：**浅色页底 + 白色圆角卡片 + 统一色板与圆角半径**，观感接近现代 Web UI，
但不引入任何 UI 框架。以下每条都是"看起来该对、实际不对"的地方。

## 一、圆角卡片：为什么不能只画圆角

`Region` 做成圆角会有锯齿 ⇒ 常规做法是"用 `GraphicsPath` 画圆角矩形 + `FillPath`"。
但 WinForms 控件的矩形区域**没有透明**，圆角外面那四个小角缝会露出控件的 `BackColor`。
如果卡片是白底而页面是浅灰，角缝就是**白色的尖角**，圆角白做。

正解：**把页面底色补进角缝**（不是靠 `TransparencyKey`，那会带出一堆副作用）。

```csharp
protected override void OnPaint(PaintEventArgs e)
{
    var g = e.Graphics;
    g.SmoothingMode = SmoothingMode.AntiAlias;

    var bounds = new Rectangle(0, 0, Width - 1, Height - 1);
    using var rounded = RoundedRect(bounds, Scale(radius, this));   // 自己的两个 helper

    using (var cardBrush = new SolidBrush(Theme.CardBackground))
        g.FillPath(cardBrush, rounded);

    using (var pageBrush = new SolidBrush(Theme.PageBackground))
    using (var region = new Region(bounds))   // 整个矩形
    {
        region.Exclude(rounded);              // 减去圆角内部 ⇒ 只剩四个角缝
        g.FillRegion(pageBrush, region);      // 用页面底色填平
    }

    // 再画标题/副标题/边框
}
```
配套的 `SetStyle`：`UserPaint | AllPaintingInWmPaint | OptimizedDoubleBuffer | ResizeRedraw`。
`BackColor` 保持**卡片色（白）**，这样卡内嵌套的容器与 `Label` 继承到的都是卡片色，
不会出现"标签底色是页面色"的割裂。

## 二、`SetClip` 只吃 `GraphicsPath`

圆角进度条如果按 `Rectangle` 裁剪，进度色块会溢出圆角。必须：

```csharp
using var clip = RoundedRect(trackBounds, radius);   // GraphicsPath
var saved = g.Save();
g.SetClip(clip);              // GraphicsPath 重载；传 Rectangle 就退回直角
g.FillRectangle(fillBrush, fillBounds);
g.Restore(saved);
```
`Restore` 千万别漏（否则后续绘制全被裁掉，症状是"只画出来一半控件"）。

## 三、文本：统一用 `TextRenderer`

```csharp
var size = TextRenderer.MeasureText(text, font,
    new Size(int.MaxValue, int.MaxValue),
    TextFormatFlags.NoPadding | TextFormatFlags.SingleLine);

TextRenderer.DrawText(g, text, font, rect, color,
    TextFormatFlags.NoPadding | TextFormatFlags.SingleLine | TextFormatFlags.VerticalCenter);
```
- `Graphics.DrawString` 与 `TextRenderer` 的**度量与基线不同**，同一个矩形里二者混用必然对不齐
  （一像素一像素地差，看起来"字有点歪"）。
- `NoPadding` 很关键：不加会在文本周围补额外边距，导致按测量值算的布局整体偏移。
- 自绘控件要自己处理 `AutoEllipsis` 语义时，用 `TextFormatFlags.EndEllipsis`。

## 四、DPI：一个 `Scale()` 走天下

```csharp
public static int Scale(int value, Control c)
{
    var dpi = c.DeviceDpi <= 0 ? 96 : c.DeviceDpi;      // 兜底，别除以 0
    return (int)Math.Round(value * dpi / 96.0);
}
```
- `ApplicationHighDpiMode = PerMonitorV2`（csproj `<ApplicationHighDpiMode>`）。
- **每一次读 `DeviceDpi` 现算**，不要缓存成静态值（跨屏拖动会变）。
- 控件在 `OnDpiChangedAfterParent` / `Resize` 时要重算 padding 并 `Invalidate()`。
- 所有"像素常量"（圆角半径、内边距、图标尺寸、行高）都过 `Scale()`，不要一半写死。

## 五、WFO1000：自定义控件属性必须标 `[DefaultValue]`

WinForms 有"设计器代码序列化分析器"（WFAC0101 / **WFO1000**）。给自定义控件加一个
可写属性、却没告诉序列化器"默认值是什么"，构建会报：

```
error WFO1000: Property 'Title' does not configure the code serialization for its property content
```

修法（每个可写且非平凡的属性都要）：

```csharp
using System.ComponentModel;

[DefaultValue("")]
public string Title { get => _title; set { _title = value ?? string.Empty; Relayout(); Invalidate(); } }

[DefaultValue(null)]  public string? Subtitle { get; set; }
[DefaultValue(12)]    public int CornerRadius { get; set; }
[DefaultValue(0D)]    public double Value { get; set; }
[DefaultValue(AppButtonStyle.Secondary)] public AppButtonStyle Style { get; set; }
```
- 枚举/自定义类型也用 `[DefaultValue]`，取值写枚举成员（要能被设计器解析）。
- 属性 setter 里要**主动布局 + `Invalidate()`**，否则改了值界面不刷新。

## 六、"界面被裁/被遮挡"排查顺序

自绘布局的缺陷**读代码看不出来**，只有渲染出来才显形。按这个顺序查：

1. **渲染成 PNG 看**。用 `DrawToBitmap` 把窗口/控件画进 `Bitmap` 存盘，
   人眼看一眼比读一百行布局代码快。
2. **行高够不够**。`TableLayoutPanel` 的 `RowStyles` 如果给了固定高度，
   而内容（多行 `Label` + 侧向排列的两个信息块）实际更高 ⇒ 被裁。
   行高按"内容实测高度 + 内边距"给，或改用 `AutoSize` 的行但**显式设置 `MinimumSize`**。
3. **容器 `Padding` 有没有包含 header 占位**。最容易漏的一条：
   卡片把标题/副标题画在自己的 `OnPaint` 里（不是子控件），子内容靠 `Padding.Top` 让开；
   一旦 `Padding` 只算了内容间距、漏了 header 顶部偏移，内容就会**压住副标题**。
   这个 bug 只在容器高度变小时才明显 —— 因为它平时"恰好"不重叠。
   ⇒ 把 `HeaderTopOffset` 计入 `ComputeHeaderHeight()`，让一处计算同时供绘制与布局使用。
4. **`AutoSize` 的连锁**。`AutoSize = true` 的父容器里放自绘子控件，常算出 0 高度 ⇒
   控件"消失"。此时给子控件显式 `Size`/`MinimumSize`。
5. **`Dock` 顺序**。`Dock` 是按控件在 `Controls` 集合里的**逆序**填充的，
   顺序错了会被另一个 `Fill` 控件整块盖住。

## 七、把"渲染 + 断言"做成用例

不依赖任何截图工具，也不用人工看图：

```csharp
// 在 STA 线程上创建窗体 → DrawToBitmap → 存 PNG → 顺便断言关键文本
var t = new Thread(() => {
    using var form = new MainForm();
    form.Show();
    Application.DoEvents();
    using var bmp = new Bitmap(form.ClientSize.Width, form.ClientSize.Height);
    form.DrawToBitmap(bmp, new Rectangle(Point.Empty, form.ClientSize));
    bmp.Save(path, ImageFormat.Png);
    Assert.Contains("25 个字符 · 4 个单词", CollectAllText(form));   // 断言真实计数
});
t.SetApartmentState(ApartmentState.STA);
t.Start(); t.Join();
```
- 无交互桌面（服务/非交互会话）时用条件退化跳过（见 `xunit-conditional-tests.md`）。
- 断言要选**稳定的语义量**（字符数/单词数文案），不要断言像素颜色 —— 那会跟着主题微调而碎。
- 把 PNG 存到 `artifacts/` 并加进 `.gitignore`；只想留证据的话把两张（空态/有内容态）**提交进 `docs/screenshots/`**。
