# xUnit：让"依赖真设备/大模型/交互桌面"的用例条件跳过

## 一、坏消息：xUnit 2.x 没有 `Assert.Skip`

实测 xUnit **2.9.3**：

- `Assert.Skip(...)` / `Assert.SkipWhen(...)` —— **不存在**（`CS0117: "Assert" 未包含...` /
  `CS0411`）。它们在 xUnit v3 才有。
- `Xunit.Sdk.SkipException` —— 类型存在，但构造函数**不是 public** ⇒ 外部程序集 new 不出来
  （`CS0122`），想用它就得靠反射，不值得。

「一个用例里发现条件不满足就跳过」这条 API 路是堵死的。

## 二、正解：运行期条件 `FactAttribute` 子类

`FactAttribute.Skip` 是**可写属性**，而特性构造函数在**用例发现阶段**执行 ⇒
把"条件不满足"翻译成"在构造函数里给 `Skip` 赋值"，得到的就是干净的、会被真实报告的跳过。

```csharp
/// 需要真实的 piper 运行时 / 语音模型才能跑
internal sealed class ModelRequiredFactAttribute : FactAttribute
{
    public ModelRequiredFactAttribute()
    {
        if (!TestPaths.HasRealModel)
            Skip = "piper runtime / voice model not present in this checkout; integration test skipped.";
    }
}

/// 需要存在音频输出设备（用例真的会出声）
internal sealed class AudioDeviceFactAttribute : FactAttribute
{
    public AudioDeviceFactAttribute()
    {
        if (!HasAudioOutputDevice)
            Skip = "No audio output device available (WaveOut.DeviceCount == 0).";
    }

    internal static bool HasAudioOutputDevice
    {
        get
        {
            try { return WaveOut.DeviceCount > 0; }
            catch (Exception ex) when (ex is InvalidOperationException or DllNotFoundException) { return false; }
        }
    }
}

/// 反向门控：只有**没有**音频设备时才有意义（验"无设备时的友好报错"）
internal sealed class NoAudioDeviceFactAttribute : FactAttribute
{
    public NoAudioDeviceFactAttribute()
    {
        if (AudioDeviceFactAttribute.HasAudioOutputDevice)
            Skip = "An output device is present, so the device-failure path cannot be exercised.";
    }
}

/// 需要一个可创建窗口的交互桌面会话
internal sealed class InteractiveDesktopFactAttribute : FactAttribute
{
    public InteractiveDesktopFactAttribute()
    {
        if (!Environment.UserInteractive)
            Skip = "No interactive desktop session; the window cannot be rendered.";
    }
}
```

要点：

- **跳过的原因必须写清楚**（缺什么、怎么补）。报告里那一行 `Skip` 文案就是下一个人唯一的线索。
- **门控谓词要能容错**：`DeviceCount` 在无驱动/无设备时会抛 `DllNotFoundException`，
  直接裸访问会让"整批用例崩掉"而不是"跳过"。
- **反向门控同样必要**：只测"有设备时能播"会漏掉"没设备时是否会抛裸异常"，
  而后者恰恰是最常在用户机器上炸的路径（见 `naudio-playback.md` §三）。
- 条件谓词**不要缓存成 static readonly 单例**去跨类共享复杂状态；简单属性每次算，成本可忽略。
- 同一个测试工程里**不要**用 `Skip` 去掩盖"环境没准备好"以外的失败 —— 那会让门控变成遮羞布。
  环境不满足 → 跳过；环境满足但行为不对 → 必须是 **FAIL**。

## 三、测试工程要引用 WinForms 应用的三件事

```xml
<PropertyGroup>
  <TargetFramework>net10.0-windows</TargetFramework>   <!-- 必须与主工程一致 -->
  <UseWindowsForms>true</UseWindowsForms>              <!-- 否则拿不到 System.Windows.Forms -->
  <IsTestProject>true</IsTestProject>
</PropertyGroup>
<ItemGroup>
  <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.14.1" />
  <PackageReference Include="xunit" Version="2.9.3" />
  <PackageReference Include="xunit.runner.visualstudio" Version="3.1.4" />
</ItemGroup>
<ItemGroup>
  <Using Include="Xunit" />                            <!-- 不然每个文件都要 using Xunit; -->
</ItemGroup>
```

## 四、测试里怎么找到工程根目录

`dotnet test` 的当前目录是**输出目录**（`bin/Debug/net10.0-windows`），
所以按"向上找解决方案文件"定位资源目录：

```csharp
static string FindRepositoryRoot()
{
    var dir = new DirectoryInfo(AppContext.BaseDirectory);
    while (dir is not null)
    {
        // ⚠️ .NET 10 的 `dotnet new sln` 默认产出 .slnx —— 只认 .sln 会一路找到盘根然后全批失败
        if (File.Exists(Path.Combine(dir.FullName, "X.sln")) ||
            File.Exists(Path.Combine(dir.FullName, "X.slnx")))
            return dir.FullName;
        dir = dir.Parent;
    }
    throw new InvalidOperationException("repository root not found");
}
```
> 本类失败的症状极具误导性：**一夜之间 55 个用例全红**，报错却是"找不到目录"，
> 看着像环境坏了。实际是 `dotnet new sln` 生成了 `.slnx` 而探测只认 `.sln`。
> 遇到"整批用例同时失败"先查**公共前置**（路径探测、共享夹具），别逐个查用例。

## 五、发布（framework-dependent）

```powershell
dotnet publish src/App/App.csproj -c Release -r win-x64 --self-contained false -o publish
```
- 默认 `-c Release` 会隐式跑一次 Release 构建 ⇒ 发布前先确保 Debug/Release 都是**零警告**。
- 大二进制资产（模型/工具）**不要**放进 `publish`：让它们在源码树旁、运行时向上查找定位，
  发布目录只有程序本体，体积和更新成本都可控。
- 发布后**实际启动一次并确认进程驻留**（几秒钟后 `tasklist` 里还在），
  别只看"publish 成功"就当能跑。

## 六、把验收结论写清楚

最终交付要有**可复现的实测数字**，以及**明确的未验证清单**：

```
Debug   96 / 通过 94 / 失败 0 / 跳过 2
Release 96 / 通过 94 / 失败 0 / 跳过 2   （2 个跳过需要音频输出设备）
未验证：真机听感播放、高 DPI 125%/150% 逐档、多显示器拖动
```
- 数字要来自真实跑过的命令，不要"预计通过"。
- **未验证的项照实写**（"代码路径已覆盖但未做听感验证"≠"已验证"）。
  声明未验证比声明通过更有价值 —— 它直接告诉下一个人该补哪一块。
