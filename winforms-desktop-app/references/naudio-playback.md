# NAudio 播放：迁移、骨架与"无设备"路径

## 一、2.x → 3.x 的破坏性改名（实测 NAudio 3.2.0）

| 2.x 写法（凭记忆常写错） | 3.x 正确写法 | 不换会怎样 |
|---|---|---|
| `new WaveOutEvent()` | `new WaveOut()` | 旧名还留着但已标 `[Obsolete]` ⇒ 告警甚至报错 |
| `output.DesiredLatency = 200;` | `output.BufferMilliseconds = 200;` | `CS1061: 不包含 DesiredLatency 的定义` |
| `output.GetPositionTimeSpan()` | 同名，但它是 **`NAudio.Utils` 上的扩展方法**（挂在 `IWavePosition`） | 不 `using NAudio.Utils;` 就报"找不到方法" |
| `WaveOut.DeviceCount` | 静态属性，直接可用 | — |

> **教训**：第三方库成员名**不要凭记忆写**。先用反射列出真实成员（或对最小工程跑一次
> `dotnet build`，让编译器给出候选），再写业务代码。凭印象改会连环报错、越改越偏。

## 二、播放器骨架（这些是踩出来的，不是模板）

```csharp
public sealed class NAudioPlayer : IAudioPlayer
{
    private WaveOut? _output;          // 懒创建并复用
    private WaveFileReader? _reader;
    private bool _stopRequested;       // 区分"手动停"与"自然播完"
    private bool _endedRaised;
    private float _volume = 1.0f;

    public void Load(string filePath)
    {
        StopOutputIfPlaying();   // 先停设备（等回调）——
        DisposeReader();         // ——再释放旧流，否则播放线程会碰已释放对象
        _reader = new WaveFileReader(filePath);   // 失败要包成自己的异常类型
        Duration = _reader.TotalTime;             // 时长只从这里来，不按文件大小估
    }

    public void Play()
    {
        WaveOut output;
        try { output = EnsureOutput(); }
        catch (Exception ex) { throw new AudioPlaybackException("无法初始化音频输出设备…", ex); }

        if (output.PlaybackState == PlaybackState.Playing) return;
        if (output.PlaybackState == PlaybackState.Paused) { output.Play(); return; }

        // 停在末尾时先倒带，否则"播完再点播放"没反应
        if (_reader!.Length > 0 && _reader.Position >= _reader.Length) _reader.Position = 0;

        try
        {
            output.Init(_reader);
            if (_volume < 1f) output.Volume = _volume;   // 音量必须在 Init 之后
            _stopRequested = false; _endedRaised = false;
            output.Play();
        }
        catch (Exception ex)
        {
            // 任何 WinMM 失败都在这里被收拢，UI 永远看不到裸 MmException
            throw new AudioPlaybackException("无法初始化音频输出设备…", ex);
        }
    }

    private WaveOut EnsureOutput()
    {
        if (_output is not null) return _output;
        // 3.x：BufferMilliseconds（旧的 DesiredLatency 已删除）。
        // ⚠️ 这里**不要**设 Volume：设备未打开时 SetVolume 会抛 MmException。
        var output = new WaveOut { BufferMilliseconds = 120, NumberOfBuffers = 3 };
        output.PlaybackStopped += OnPlaybackStopped;   // 整个生命周期只订阅这一次
        return _output = output;
    }
}
```

### 位置（进度条）取值

```csharp
var output = _output;
if (output is not null && output.PlaybackState != PlaybackState.Stopped)
    position = output.GetPositionTimeSpan();   // 需要 using NAudio.Utils;
else
    position = reader.CurrentTime;             // 未播放/已停：以流位置为准
// 再 clamp 到 [TimeSpan.Zero, reader.TotalTime]
```
- 播放中用**设备位置**（跟随实际出声），暂停/停止用**流位置**，二者偏差会让人以为"进度乱跳"。
- 上面两步都要 try 住 `InvalidOperationException` / `ObjectDisposedException`。

### `PlaybackStopped` 的三态判别

```csharp
private void OnPlaybackStopped(object? sender, StoppedEventArgs e)
{
    var error = e.Exception;
    var naturalEnd = error is null && !_stopRequested;   // 关键：靠标志位而不是状态
    ...
    if (error is not null) { PlaybackError?.Invoke(this, new(e.Exception)); return; }
    if (naturalEnd && !_endedRaised) { _endedRaised = true; PlaybackEnded?.Invoke(this, EventArgs.Empty); }
}
```
- 不设 `_stopRequested` ⇒ 手动 `Stop()` 也会触发 `PlaybackEnded`，UI 会闪一下"播完了"。
- `_endedRaised` 防重复触发（一次播放只通知一次）。
- **自然播完后不要把流倒带**（让 UI 能显示 100%）；手动停/出错才倒带。

## 三、"没有音频输出设备"是一个必须支持的合法环境

本机实测 `WaveOut.DeviceCount == 0`。此时：

| 操作 | 应当的行为 |
|---|---|
| `Load(path)` / 读 `TotalTime` | **正常工作**（只碰文件，不碰设备） |
| `Play()` | 抛**自己的** `AudioPlaybackException`，消息里写"请检查系统播放设备" |
| 设 `Volume` | 静默忽略（`MmException` 吞掉即可，不是致命错误） |
| `Stop()` / `Dispose()` | 静默成功（幂等，不能因为设备没了就抛） |
| `IsPlaying` / `IsPaused` | 返回 `false`（`_output` 为 null 时不要 NRE） |

`Dispose()` 要幂等：`_disposed` 早返回 → 退订事件 → `Stop()` → `Dispose()` 设备 → 释放流。

**典型失败**：`EnsureOutput()` 里顺手写了 `output.Volume = _volume;` ⇒ 创建播放器那一刻就
抛 `MmException: BadDeviceId calling waveOutSetVolume`，而这个异常类型不是调用方预期捕获的，
于是整个"加载并显示时长"的路径连带挂掉。**先想清楚"这一步需要设备吗"再放代码。**

## 四、UI 侧

- 进度刷新用 `System.Windows.Forms.Timer`（间隔 100~200 ms 够用；`Thread.Sleep` 轮询不行）。
- 时间格式化要处理 >1 h：`mm:ss`，超过 1 小时才升到 `h:mm:ss`（小时**不补零**）。
- 事件的 `sender` 在音频线程 ⇒ 在 handler 里立刻 `Invoke` 回 UI 线程再碰控件。
