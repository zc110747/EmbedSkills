---
name: wpf-realtime-sim
description: WPF+MVVM 实时仿真/遥测看板：解耦后台步进线程、30FPS 刷新、自更新 Canvas 趋势图、暗色主题（含 ComboBox 模板）、离屏 PNG 验证。
agent_created: true
---
# WPF real-time simulation dashboard (no charting dependency)

Reusable structure when a WPF/MVVM app must visualize a model that steps faster
than the UI (e.g. 1 kHz physics, 30–60 FPS charts).

## Architecture (keep UI out of the math)
- **Core layer** (UI-agnostic, SI units): pure model + controllers + a
  `SimulationEngine` that owns the clock and produces a `Telemetry` snapshot each step.
- **View model**: holds the engine, runs the stepping loop on a **background Task**,
  and refreshes display values on a `DispatcherTimer` (~33 ms).
- **View**: binds only to telemetry / display properties. Never computes.

## Decoupled stepping (critical)
- Background `Task` runs a **fixed-timestep accumulator** (see below) while running;
  yield the CPU when caught up (do NOT busy-spin) and `Thread.Sleep(5)` when paused.
  On pause, keep the pacer clock pinned to the current stopwatch reading every idle
  tick so resume doesn't fast-forward.
- ⚠️ **Never advance the clock with `lastSimTime = now`.** Measuring `realDt = now −
  lastSimTime` and then snapping `lastSimTime = now` each iteration **discards the
  sub-timestep remainder**. The moment the loop iterates faster than one timestep
  (sub-millisecond — which happens as soon as you stop busy-spinning), the remainder
  never accumulates to a full step and the **sim clock crawls / looks frozen**: values
  creep up and the trend chart shows a single vertical line at the right edge (all
  samples share ~one timestamp). Correct form — KEEP the remainder:
  ```csharp
  double elapsed = now - _lastTime;
  if (elapsed < TimeStep) { Thread.Sleep(1); continue; }        // yield, don't spin
  int steps = (int)(elapsed / TimeStep);
  if (steps > MaxStepsPerTick) { steps = MaxStepsPerTick; _lastTime = now; } // stall: bounded burst + resync
  else _lastTime += steps * TimeStep;                            // keep sub-step remainder
  for (int i = 0; i < steps; i++) engine.Step(TimeStep);
  ```
  Encapsulate in a small unit-testable `FixedStepPacer` (virtual-clock test: N sub-ms
  iterations must yield ≈ N·dt/TimeStep steps). A comparison test modelling the old
  `lastSimTime = now` snap and asserting **0 steps** documents the regression.
- **Diagnostic** — one vertical line at the chart's right edge + values barely moving
  = it's the clock, not the controller. Cross-check by hand: with a small `J`, the
  computed `dω/dt = (Kt·I − Tf)/J` says the motor should reach target in a fraction of
  a second; if displayed speed is only a few % of target, the clock advanced only ms.
- UI timer: copies telemetry into `double` display props (use `SetField` so no
  notification fires when unchanged) — do **not** let the WPF timer drive physics.
  Read **all** display values from the **same** telemetry snapshot each frame; mixing
  in live reads of a controller object yields mutually inconsistent numbers (torn read,
  e.g. target-current from the last step vs. a newer PID output).

## Self-updating Canvas chart (replace LiveCharts)
- `RealTimeChart` UserControl: `DependencyProperty DataSource` (the telemetry
  object) + `PrimaryPath`/`SecondaryPath` (property names) + `WindowSeconds`
  + `AutoScale`.
- Internal `DispatcherTimer` (33 ms): `Sample()` reflects `DataSource.GetType()
  .GetProperty(path).GetValue(ds)` at `DataSource.Time`, pushes `(t,v)` into a
  ring buffer, trims to the window, and on `t < lastT` clears buffers (engine
  reset detection). Cache `PropertyInfo`.
- ⚠️ **Do NOT `Children.Clear()` + rebuild the visual tree every frame.** With several
  charts that creates ~10³ WPF objects/frame + a full layout pass each tick and drops
  the UI to single-digit FPS. Instead: a **persistent grid layer** (lines/labels/legend)
  rebuilt only when the canvas size changes; **persistent `Polyline`s** whose `Points`
  are updated in place (structs — no UIElement churn); update label `Text` only (cheap).
  Cap buffer length (e.g. 4000) so a frozen clock (paused) can't leak memory.

## Decimal-aware number box (avoid rounding tiny values)
- `LabeledNumberBox` exposes `Value` (double, `BindsTwoWayByDefault`). A
  `MultiBinding` + `IMultiValueConverter` takes `(value, decimals)` so each box
  formats with its own precision (e.g. inductance 0.005 must show 0.005 not 0.01).
  `ConvertBack` returns `[parsedDouble, Binding.DoNothing]`.

## Dark theme: the stock ComboBox template ignores Background
- The built-in WPF `ComboBox` template paints itself with **hard-coded light system
  brushes** and does **not** honour `Background`/`Foreground`. On a dark theme you get a
  white closed box with near-white text — effectively unreadable (a classic "the dropdown
  is unreadable" bug, and setting `Background` on a plain `Style TargetType="ComboBox"`
  silently does nothing).
- Fix: a full `ControlTemplate` in the theme dictionary:
  - a `ToggleButton` with its own template (themed `Border` + arrow `Path`;
    `IsChecked="{Binding IsDropDownOpen, RelativeSource=TemplatedParent, Mode=TwoWay}"`),
  - a non-hit-testable `ContentPresenter` showing `SelectionBoxItem`
    (`ContentTemplate`/`ContentStringFormat` template-bound),
  - a `Popup` (`IsOpen="{TemplateBinding IsDropDownOpen}"`) whose child is a themed
    `Border > ScrollViewer > StackPanel IsItemsHost="True"` (for the drop-down list),
  - plus a `ComboBoxItem` template with `IsHighlighted` (hover) / `IsSelected` triggers
    or the list rows stay light.
- Keep theme styles in a **standalone `ResourceDictionary`** (e.g. `Themes/Dark.xaml`)
  merged into `App.xaml` via `<ResourceDictionary.MergedDictionaries>` — prefer this over
  inline `Application.Resources` so a non-UI host (headless tool/tests) can load the SAME
  dictionary. Implicit styles (no `x:Key`, `TargetType=...`) merged at
  `Application.Resources` apply app-wide; if you keep the old inline styles next to the
  merged dict you get duplicate-key conflicts.

## Headless PNG verification (rasterise the REAL window off-screen)
Use when CI / a sandbox has no interactive desktop but you must produce a visual that
proves the UI (dark theme, verdict readouts, charts) actually renders.
- **A never-shown `Window` rasterises BLANK.** `RenderTargetBitmap.Render(window)` on a
  Window that was never `Show()`n yields an empty image (the top-level visual has no
  presentation source). Instead **detach the window's content** into a plain host and
  render that:
  ```csharp
  var root = (FrameworkElement)window.Content;
  window.Content = null; root.Margin = new Thickness(0);
  var host = new Border { Background = window.Background, Child = root,
                          DataContext = vm, Width = w, Height = h };
  host.Measure(new Size(w,h)); host.Arrange(new Rect(0,0,w,h)); host.UpdateLayout();
  var bmp = new RenderTargetBitmap((int)w,(int)h,96,96,PixelFormats.Pbgra32);
  bmp.Render(host);            // -> PngBitmapEncoder -> file
  ```
  Make the host as tall as the content so a `ScrollViewer` isn't clipped (renders every
  card, not just the viewport). Keep the window background on the host (the bare content
  grid is transparent).
- **A console EXE hosting WPF has no `Application`** → app-level merged dictionaries /
  implicit styles do NOT apply, so `{StaticResource Card}` throws `XamlParseException`
  ("cannot find resource") and controls fall back to the light system theme. Instantiate
  the App class (`new MyApp.App()`, which sets `Application.Current`), and if the theme
  dict's **relative** `MergedDictionaries Source` does not resolve outside a real
  `Application.Run`, load it explicitly by pack URI:
  `new ResourceDictionary { Source = new Uri("pack://application:,,,/MyApp;component/Themes/Dark.xaml") }`.
  Name-clash trap: `new App()` can bind to the **namespace** `MyApp` → fully qualify
  `new MyApp.App()`.
- **`DispatcherTimer`-driven charts/UI never tick off-screen** (no message pump), and
  `Loaded` may not fire on an unshown window. Don't rely on them — add a public entry
  point on the control that runs the SAME render path on a supplied series, e.g.
  `chart.RenderTrajectory(primary, secondary)` (clears buffers, sets `_lastT`, calls the
  normal `Render()`), and drive the model deterministically with a
  `RunHeadless(preset, seconds)` that steps N times and records a history — not the
  real-time loop.
- **Resolve `x:Name` references BEFORE detaching** the content: the name scope belongs to
  the Window, so `window.FindName("Chart")` works while attached, but `root.FindName`
  fails after the content is reparented.

## Verification
- Build **Debug and Release**; assert 0 warnings. Unit-test the Core model/controllers
  directly (no UI needed): assert physical trends (startup current high→falls,
  back-emf balances V, load↑→speed↓), not just "runs".
- **Headless CI can now render a visual** — use the off-screen PNG technique above
  (render the real window: theme, readouts, charts) instead of only trusting the XAML
  BAML compile. Better yet, make the acceptance check *independent of the simulation*:
  a closed-form analytic solver (no time stepping, no controller) whose equilibrium the
  sim must match — then a mismatch genuinely FAILS rather than the sim validating itself.
- Tuning PID: check closed-loop damping ratio ζ = (Kp·Kt)/(2√(Ki·Kt·J)); underdamped
  (ζ<0.3) causes overshoot — raise Kp or lower Ki. For a cascaded loop, an outer PI
  with a **slewing setpoint** overshoots because it integrates the speed lag; **freeze
  the outer integrator during the ramp** (integral hold) and let an acceleration
  feed-forward carry the ramp current.
