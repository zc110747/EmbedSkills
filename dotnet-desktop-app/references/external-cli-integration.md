# 从 .NET 安全调用外部 CLI（长跑、有管道、要能取消）

场景：应用把某个本地命令行工具（TTS、编解码、转换器）当引擎用。
**这类集成的 bug 几乎全在"进程与管道"上**，不在业务代码里。

## 一、起点：`ArgumentList` 而不是拼字符串

```csharp
var psi = new ProcessStartInfo
{
    FileName = exePath,
    UseShellExecute = false,          // 必须：否则拿不到 stdin/stdout 重定向
    CreateNoWindow = true,
    RedirectStandardInput = true,
    RedirectStandardOutput = true,
    RedirectStandardError = true,
    WorkingDirectory = Path.GetDirectoryName(exePath) ?? Environment.CurrentDirectory,
};
psi.ArgumentList.Add("--model");       psi.ArgumentList.Add(modelPath);
psi.ArgumentList.Add("--config");      psi.ArgumentList.Add(configPath);
psi.ArgumentList.Add("--output_file"); psi.ArgumentList.Add(outputPath);
```
- **绝不**用 `Arguments = $"-m \"{path}\""`：路径里的空格/引号/中文会把你坑掉，
  而且拼错时不报错、只是参数被切开（表现为"工具说没给模型"）。
- `ArgumentList` 由运行时负责正确的转义与引用规则。

## 二、正文走 stdin，且要能取消

```csharp
await process.StandardInput.WriteAsync(text.AsMemory(), cancellationToken);
process.StandardInput.Close();      // 必须关：很多 CLI 读到 EOF 才开始干活
```
- 大文本**不要**塞进命令行参数（有长度上限，且会进进程列表）。
- `WriteAsync` 要传 `CancellationToken`，否则取消时可能卡在写管道上。

## 三、两个输出流必须**并发**读 —— 否则死锁

管道缓冲区（通常 4~64 KB）满了以后，子进程会**写阻塞**，而你在等它退出 ⇒ 经典死锁。
长文本/verbose 输出特别容易触发。

```csharp
var stdoutTask = process.StandardOutput.ReadToEndAsync(ct);
var stderrTask = process.StandardError.ReadToEndAsync(ct);
await process.WaitForExitAsync(ct);
var stdout = await stdoutTask;
var stderr = await stderrTask;
```
- **不要**写 `process.WaitForExit(); var s = process.StandardOutput.ReadToEnd();`（先等后读也会死锁）。

## 四、超时＝杀掉整棵进程树

```csharp
using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
timeoutCts.CancelAfter(options.ProcessTimeout);          // 例如 10 分钟
try { await process.WaitForExitAsync(timeoutCts.Token); }
catch (OperationCanceledException)
{
    TryKillTree(process);                                 // 见下
    return cancellationToken.IsCancellationRequested ? TtsResult.Cancelled() : TtsResult.Fail("合成超时");
}

static void TryKillTree(Process p)
{
    try { if (!p.HasExited) p.Kill(entireProcessTree: true); }   // 必须带 tree
    catch (Exception ex) when (ex is InvalidOperationException or NotSupportedException) { }
}
```
- `Kill()` **不带 `entireProcessTree: true`** ⇒ 只杀父进程，工具派生的子进程会**变成孤儿继续跑**，
  于是"取消后 CPU 还在 100%""下次运行说设备忙"。
- 超时必须用**链式 CTS**，让"用户取消"和"到点"都走同一条收尾路径。

## 五、成功判据 = 退出码 + 产物校验（两者都要）

```csharp
if (process.ExitCode != 0)
    return TtsResult.Fail($"引擎退出码 {process.ExitCode}", diagnostics: stdout + stderr);

if (!File.Exists(outputPath))          return TtsResult.Fail("引擎未生成输出文件", diag);
if (!IsValidOutput(outputPath))        return TtsResult.Fail("输出文件格式无效", diag);
```
- **退出码 0 不代表产物正确**：0 字节文件、半截文件、格式不对都出现过。
- 反过来，退出码非 0 但产物其实写好了也不能当成功（说明工具进入了未定义状态）。
- 用**解码器**校验而不是看大小（WAV → `WaveFileReader.TotalTime > TimeSpan.Zero`；
  RIFF 头 `"RIFF"`/`"WAVE"` 再做一次粗筛）。

## 六、产物原子落地：临时文件 + 重命名

**绝不让半截文件占用用户选的路径。**

```csharp
var dir  = Path.GetDirectoryName(finalPath)!;
var temp = Path.Combine(dir, $".{Path.GetFileNameWithoutExtension(finalPath)}.{Guid.NewGuid():N}.tmp.wav");
try
{
    // 让引擎写 temp
    ... 校验 temp ...
    File.Move(temp, finalPath, overwrite: true);   // 同目录内的重命名是原子操作
}
catch { TryDelete(temp); throw; }
finally { TryDelete(temp); }   // 兜底：异常路径不留垃圾
```
- 临时文件放在**目标目录**（不是 `%TEMP%`）：跨卷 `Move` 会退化成"拷贝+删除"，就不原子了。
- 临时文件用点号开头 + 带 GUID，避免与用户的文件名撞车、也避免被当成正常产物列出来。
- 任何失败路径都要删临时文件，并且**删掉"已经写进目标路径的无效产物"**。

## 七、可诊断性：把两路输出塞进结果对象

```csharp
public sealed record TtsResult(bool Success, string? OutputWavPath, string? ErrorMessage,
                               string? Diagnostics, TimeSpan AudioDuration, bool Cancelled);
```
- 只有"退出码 1"是没法排查的。把 stdout + stderr 原文连同一条命令摘要一起留在 `Diagnostics`。
- 失败消息给人看（中文、说清下一步），`Diagnostics` 给排查看（原文，不做美化）。
- **不要**把 `Diagnostics` 塞进 UI 的普通提示里 —— 但也不要丢掉。

## 八、进程之外：路径与缓存

- 引擎的可执行文件、模型、配置**按"向上查找"探测**（从程序集目录往上找若干层），
  不要硬编码绝对路径，也不要把几十 MB 的模型拷进 `bin/`。
- 版本/哈希核对放**下载脚本**里（见 `piper-offline-tts/references/model-provisioning-and-licensing.md`），
  运行时只做"存在性 + 可解析"的轻量预检。
- 启动前做一次环境预检并缓存结果（`Ready / MissingExecutable / MissingModel / MissingConfig`），
  UI 就能在点按钮之前告诉用户"缺什么"，而不是点完再报错。
