# 运行时与模型的获取、哈希核对与许可

Piper 是"**引擎**（可执行文件）"+"**声学模型**（.onnx + .onnx.json）"两件独立资产，
许可、体积、更新节奏都不同。交付时必须分别说明来源。

## 一、两件资产的事实（实测核对过）

| 资产 | 来源 | 版本 | 许可 |
|---|---|---|---|
| Piper 运行时（Windows x64） | GitHub `rhasspy/piper` releases，资产 `piper_windows_amd64.zip` | `2023.11.14-2`（内含 piper 1.2.0） | **MIT** © 2022 Michael Hansen |
| 语音模型 `en_US-ljspeech-medium` | HuggingFace `rhasspy/piper-voices`，路径 `en/en_US/ljspeech/medium/` | — | 数据集 **LJ Speech = 公有领域**；模型卡写明 **"US English female voice"** |

- **性别来自模型卡/数据集，不是来自文件名**。要"女声"就得去读模型卡的描述并写进文档，
  不要靠"ljspeech 听起来像女声"这类推断。
- 模型是 **22,050 Hz / 单声道 / 16 bit**，可从 `*.onnx.json` 的 `audio.sample_rate` 读出。

## 二、哈希核对（不要跳过）

Piper 官方发布的 **`voices.json`** 里给了每个模型文件的 **MD5** —— 这是权威清单。
下载脚本必须逐文件核对并在不一致时**显式失败退出**。

```
piper_windows_amd64.zip   SHA-256  f3c58906402b24f3a96d92145f58acba6d86c9b5db896d207f78dc80811efcea
en_US-ljspeech-medium.onnx        MD5  109d552e9dd78d92d1169a7edd6de38d
en_US-ljspeech-medium.onnx.json   MD5  0668112b8b3ac5bb4b12c2b1a366776a
```

> 这几条哈希属于"**版本化的常量**"：换 release / 换模型就必须重新核对并更新，
> 它们不是永久真值。写进脚本时**连同来源 URL 一起注释**。

## 三、目录布局：模型不进输出目录

```
<repo>/tools/piper/piper.exe            # 解压出的运行时（含 espeak-ng-data/）
<repo>/tools/piper/espeak-ng-data/      # 必须与 exe 同级
<repo>/models/<voice>.onnx              # 声学模型
<repo>/models/<voice>.onnx.json         # 模型配置（不是"下载的元数据"）
```

- `.gitignore` 里排除 `tools/piper/` 与 `models/*.onnx`（几十 MB 级二进制不进版本库）。
- **保留**小而关键的元数据入库：`models/voice-metadata.json`、`MODEL_CARD` 等
  —— 它们让"这是什么声音、什么许可"可查，且体积可忽略。
- csproj **不要**把 `models/`、`tools/` 拷进输出目录；运行时用"从程序集目录向上查找"定位
  （见 `winforms-desktop-app/references/external-cli-integration.md` §八）。
  好处：`dotnet publish` 产物只有程序本体，模型更新不用重新发布。

## 四、下载脚本要点（PowerShell）

```powershell
[CmdletBinding()]
param([string] $RepositoryRoot, [switch] $Force)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'   # 不设这个，Invoke-WebRequest 会慢一个量级
```

- ⚠️ **不要在 `param` 的默认值里用 `$PSScriptRoot`**：用 `-File` 启动时它可能为空，
  报 `Cannot bind argument to parameter 'Path' because it is an empty string`。
  在**脚本体内**解析：

```powershell
if (-not $RepositoryRoot) {
    $scriptDirectory = $null
    if ($PSScriptRoot) { $scriptDirectory = $PSScriptRoot }
    elseif ($MyInvocation.MyCommand.Path) { $scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path }
    $RepositoryRoot = if ($scriptDirectory) { Split-Path -Parent $scriptDirectory } else { (Get-Location).Path }
}
```

- 下载优先用 `curl.exe -L --fail --silent --show-error -o <dst> <url>`，
  并**检查 `$LASTEXITCODE`**（`--fail` 让 HTTP 4xx/5xx 变成非零退出）；
  没有 curl.exe 时回退 `Invoke-WebRequest`（更慢，要提示）。
- 校验用 `Get-FileHash -Algorithm SHA256` / `-Algorithm MD5`，比对失败 ⇒ 删掉半截文件 + 抛错退出。
  不要"警告一下继续"。
- 已存在且哈希正确的文件**默认跳过**（幂等，可反复跑）；`-Force` 才重下。
- 脚本末尾做一次**自检**（例如 `piper.exe --version`），把"下载完其实跑不起来"提前暴露。

## 五、交付文档里必须写清的四件事

1. **哪些二进制需要用户自行获取**（本项目的 `.onnx` 与 `tools/piper/` 都不入库）。
2. **来源与版本**（release tag / 仓库路径），并给出**可点击的完整 URL**。
3. **许可**（引擎 MIT；模型基于公有领域的 LJ Speech，模型卡描述女声），
   以及"再分发时你需要遵守什么"。
4. **哈希**（上面的 SHA-256 / MD5），并说明**在哪里能查到权威清单**（`voices.json`）。

> 只写"下载 piper 模型"而不写来源/版本/哈希/许可，等于没交付：
> 下一个人无法复现，也无法判断能不能再分发。
