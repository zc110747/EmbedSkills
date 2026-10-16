# 让同一个 .NET GUI 程序同时当命令行工具用

需求形态：一个 WinForms 桌面程序，老板/用户又要求"能写进脚本，跑一条命令就把活干完"。
这里只讲**实测踩到的坑**与判据，不重复 CLI 参数解析之类的常识。

## 1. 子系统的取舍（先决定这件事）

| 方案 | 双击 exe | 从 cmd 运行 | 代价 |
|---|---|---|---|
| `OutputType=WinExe`（windows 子系统） | ✅ 不闪控制台 | ❌ 提示符**不等待**、stdout 默认无效 | 需要手工附着控制台 |
| `OutputType=Exe`（console 子系统） | ❌ 闪一个黑框 | ✅ 一切正常 | GUI 观感被破坏 |

结论：**保留 `WinExe`，在"有参数"时手工附着父进程控制台**；
再配一个批处理包装器解决"提示符不等待"。

## 2. WinExe 打印不出东西：`AttachConsole` 与**顺序陷阱**

GUI 子系统的进程从控制台启动时**不会自动附着**到该控制台，所以直接 `Console.WriteLine`
在真实 cmd 窗口里什么都看不到。修法是标准动作：

```csharp
[DllImport("kernel32.dll", SetLastError = true)] static extern bool AttachConsole(int pid);
[DllImport("kernel32.dll")]                      static extern IntPtr GetConsoleWindow();

public static void Attach()
{
    var hasConsole = GetConsoleWindow() != IntPtr.Zero;
    if (!hasConsole) hasConsole = AttachConsole(-1 /* ATTACH_PARENT_PROCESS */);

    // ⚠️ 必须放在 AttachConsole 之后读！
    if (hasConsole && !Console.IsOutputRedirected && SetConsoleOutputCP(65001))
        SetConsoleCP(65001);

    Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false))
        { AutoFlush = true });
}
```

### 为什么顺序不能反（这条最容易写错）

`Console.IsOutputRedirected` 的判据是"stdout 句柄能不能当控制台用"。
**未附着控制台的进程**，即使它的 stdout 句柄其实是父进程的控制台句柄，
`GetConsoleMode` 也会失败并报 `ERROR_INVALID_HANDLE` ⇒ 于是 `IsOutputRedirected == true`。

如果你写成"看起来已重定向就跳过附着"，那么在**真实 cmd 窗口**里就会：
不附着 → 把内容写进一个根本不可用的控制台句柄 → **静默无输出**（退出码还是 0）。
而在"stdout 是管道"的测试环境里它却是好的 —— 于是这个 bug 在自动化测试里**永远不会暴露**。

> 判据：`.NET` 里凡是"控制台/重定向"的判断，都要先问"此时进程到底附着没附着"。
> 顺序错一次，症状是"测试全绿、真人一用就没输出"。

## 3. 输出到底去哪儿了：用探针，别用猜

"抓不到输出"≠"程序没输出"。先把下面这组事实打成一行日志（写 `%TEMP%` 文件，不依赖控制台）：

```
GetConsoleWindow() / AttachConsole 返回值 / IsOutputRedirected(attach 前) /
IsOutputRedirected(attach 后) / OpenStandardOutput() == Stream.Null? / stream.GetType().Name
```

实测到的两种典型取值（同一份二进制）：

| 场景 | attach | redirected(后) | 结果 |
|---|---|---|---|
| 直接跑 exe，stdout 是管道 | True | True | 走"继承句柄"分支，输出被管道**捕获** ✅ |
| 经 `cmd.exe`（批处理）跑 | True | 视 shell 而定 | 输出被路由到**控制台** ⇒ 管道抓不到，但真人看得见 ✅ |

⇒ **`.cmd` 一旦介入，stdout 的归属就可能变**。不要用"我这边没抓到"推断"程序没输出"。

## 4. 批处理包装器：解决"提示符不等待"

WinExe 从 cmd 交互式提示符启动时，cmd **不会**等它结束，输出会和下一个提示符混在一起。
**在批处理里调用 GUI 程序，cmd 会等待**，于是：

```bat
@echo off
set "APP=%~dp0EnglishAudio.exe"
if not exist "%APP%" set "APP=%~dp0publisher\EnglishAudio.exe"
if not exist "%APP%" ( echo [ERROR] exe not found. & pause & exit /b 1 )
"%APP%" %*
exit /b %ERRORLEVEL%
```

- 同一份内容放在"仓库根"和"发布目录"都能用（用 `%~dp0` 逐级兜底找 exe）。
- **不要**在失败时自动 `pause`：`for %f in (*.md) do app.cmd "%f"` 会在第一次失败时永久挂住。
  `pause` 只留给"双击场景"的启动器。
- 仍遵守既有约定：**CRLF + 纯 ASCII**。

## 5. 退给脚本的契约

- **分级退出码**，不要只有 0/1：参数错、输入不存在、编码不支持、语言不支持、缺依赖、合成失败
  各给一个码，脚本才可能区分"我的输入不对"和"环境没装好"。
- 业务错误写 **stderr**，进度/结果写 **stdout**；这样重定向 stdout 到文件仍然干净。
- stdout 失败不能让业务失败：包一层"吞 I/O 异常的 TextWriter"，否则"打印不出来"会升级成"转换失败"。

```csharp
internal sealed class SafeTextWriter(TextWriter inner) : TextWriter
{
    public override Encoding Encoding => inner.Encoding;
    public override void Write(string? v) => Guard(() => inner.Write(v));
    public override void WriteLine(string? v) => Guard(() => inner.WriteLine(v));
    static void Guard(Action a)
    {
        try { a(); }
        catch (Exception ex) when (ex is IOException or ObjectDisposedException or UnauthorizedAccessException) { }
    }
}
```

## 6. 别把 CLI 逻辑塞进 Form

`Main` 里按 `args.Length` 分流，CLI 走一套独立的编排类；两者共用同一批 Service
（引擎、校验、路径解析、错误包装）。这样"命令行能干的"和"界面能干的"永远不会走偏，
也给 CLI 留出可注入的 `TextWriter` 以便测试（不必真去读控制台）。
