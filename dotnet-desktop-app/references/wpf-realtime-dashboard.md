# WPF 实时看板：配速、自绘曲线、暗色主题与离屏渲染

适用场景：被仿真的对象步进快于 UI（例如物理 1 kHz、图表 30~60 FPS），
不允许引入图表库，且要在无交互桌面的环境里出一张能证明界面渲染正常的图。

## 1. 固定步长配速器（最容易写错的一段）

```csharp
double elapsed = now - _lastTime;
if (elapsed < TimeStep) { Thread.Sleep(1); continue; }        // 让出 CPU，不忙等
int steps = (int)(elapsed / TimeStep);
if (steps > MaxStepsPerTick) { steps = MaxStepsPerTick; _lastTime = now; } // 停滞：有界突发 + 重同步
else _lastTime += steps * TimeStep;                            // 保留不足一步的余数
for (int i = 0; i < steps; i++) engine.Step(TimeStep);
```

- ❌ `_lastTime = now` 每轮直接对齐当前时刻，**丢弃亚步长余数**。一旦循环迭代快于
  一步（停止忙等后必然发生），余数永远攒不满一步 ⇒ 仿真时钟只前进几毫秒/秒，
  表现为"数值缓慢爬升 + 曲线在右缘一条竖线（所有样本同一时间戳）"。
- 暂停时**每轮空转都把 `_lastTime` 钉到当前 stopwatch 读数**，否则恢复瞬间会追帧快进。
- 抽成可单测的 `FixedStepPacer`：给定 N 次亚毫秒迭代，步数应 ≈ `N·dt/TimeStep`。
  再写一条"旧写法应得 0 步"的对照用例，把回归钉住。

**诊断**：数值几乎不动 + 曲线单竖线 ⇒ 先怀疑时钟，不是控制器。
手算一次量级（用已知的加速度/增益估"应在几百毫秒内到目标"），若显示只有目标的百分之几，
就是时钟只走了几毫秒。

## 2. 自绘趋势图（替代图表库）

- `UserControl` 暴露 `DependencyProperty`：`DataSource`（快照对象）+ `PrimaryPath` /
  `SecondaryPath`（属性名）+ `WindowSeconds` + `AutoScale`。
- 内部 `DispatcherTimer`（33 ms）：按 `DataSource.Time` 取值，推 `(t,v)` 进环形缓冲，
  裁到窗口长度；`t < lastT` 视为引擎重置，清空缓冲。`PropertyInfo` 缓存，别每帧反射查找。
- ⚠️ **不要每帧 `Children.Clear()` 重建**：多图时每帧上千个 UIElement + 全量布局，
  帧率掉到个位数。正确做法：
  - 网格/刻度/图例做成**持久层**，仅在画布尺寸变化时重建；
  - 曲线用持久 `Polyline`，**原地更新 `Points`**（结构体，无 UIElement churn）；
  - 标签只改 `Text`；
  - 缓冲长度设上限（如 4000），否则暂停时时钟冻结也会缓慢泄漏。
- 自动缩放要留死区，避免一条直线时纵轴反复抖。

## 3. 小数精度输入框

`LabeledNumberBox.Value`（`double`，`BindsTwoWayByDefault`）+ `MultiBinding`
绑 `(value, decimals)`，每个框显示自己的精度（0.005 不能显示成 0.01）。
`ConvertBack` 返回 `[parsedDouble, Binding.DoNothing]`，避免回写触发源更新。

## 4. 暗色主题里的 ComboBox

内置模板用硬编码浅色系统画刷，**不认 `Background`/`Foreground`**；给
`Style TargetType="ComboBox"` 设 `Background` 是**静默无效**的，结果就是白底近白字。

必须整套 `ControlTemplate`：

- `ToggleButton` 自定义模板（主题 `Border` + 箭头 `Path`，
  `IsChecked="{Binding IsDropDownOpen, RelativeSource=TemplatedParent, Mode=TwoWay}"`）；
- 不可命中测试的 `ContentPresenter` 显示 `SelectionBoxItem`
  （`ContentTemplate` / `ContentStringFormat` 用 TemplateBinding）；
- `Popup`（`IsOpen="{TemplateBinding IsDropDownOpen}"`），子级
  `Border > ScrollViewer > StackPanel IsItemsHost="True"`；
- 外加 `ComboBoxItem` 模板，补 `IsHighlighted` / `IsSelected` 触发器，否则下拉行仍是浅色。

主题放独立 `ResourceDictionary`（如 `Themes/Dark.xaml`），用
`<ResourceDictionary.MergedDictionaries>` 合并进 `App.xaml`：这样**非 UI 宿主**
（headless 工具/测试）能加载同一份。隐式样式（无 `x:Key`）在 `Application.Resources`
合并后全局生效；旧内联样式与新字典并存会触发重复键冲突。

## 5. 离屏渲染真实窗口

**从未 `Show()` 的 `Window` 渲染出来是空白**（顶层视觉缺少呈现源）。
把内容摘出来挂到一个普通宿主上：

```csharp
var root = (FrameworkElement)window.Content;
window.Content = null; root.Margin = new Thickness(0);
var host = new Border { Background = window.Background, Child = root,
                        DataContext = vm, Width = w, Height = h };
host.Measure(new Size(w, h)); host.Arrange(new Rect(0, 0, w, h)); host.UpdateLayout();
var bmp = new RenderTargetBitmap((int)w, (int)h, 96, 96, PixelFormats.Pbgra32);
bmp.Render(host);   // -> PngBitmapEncoder -> file
```

- 宿主高度按**内容全高**，否则 `ScrollViewer` 只渲染视口，卡片被截掉。
- 背景色要带到宿主（裸内容网格透明，出图是黑/透明底）。
- **控制台 exe 托管 WPF 时没有 `Application`** ⇒ app 级合并字典与隐式样式不生效，
  `{StaticResource ...}` 抛 `XamlParseException`，控件退回浅色系统主题。
  解决：`new MyApp.App()`（**全限定**，否则 `App` 可能绑到命名空间），
  并按 pack URI 显式加载主题：
  `new ResourceDictionary { Source = new Uri("pack://application:,,,/MyApp;component/Themes/Dark.xaml") }`。
- `DispatcherTimer` 在无消息泵时不 tick、`Loaded` 可能不触发 ⇒ 控件要提供
  `RenderSeries(primary, secondary)` 这类**同步入口**，走同一套渲染路径；
  数据用确定性 `RunHeadless(preset, seconds)` 逐步进 N 次生成，而不是跑实时循环。
- **`x:Name` 必须在摘出 Content 之前解析**（命名作用域属于 Window），
  重挂父级后 `root.FindName` 找不到。

## 6. 验收

- Debug/Release 双构 0 警告；Core 层单测直接断言物理趋势（启动量高→回落、
  负载↑→转速↓），而不是只断言"能跑"。
- 更硬的做法：让验收**独立于仿真**——用闭式解算器（不步进、不控制）求平衡点，
  仿真必须对上；对不上才算真 FAIL，否则是仿真自证。
- 无交互桌面下用上面的离屏 PNG，断言关键文本存在、曲线点数 > 0，而不是只信 XAML 编译通过。
