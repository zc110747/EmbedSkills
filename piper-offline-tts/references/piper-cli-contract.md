# Piper CLI 契约（实测 1.2.0 / Windows release 2023.11.14-2）

## 一、调用形状

```
piper.exe --model <voice>.onnx --config <voice>.onnx.json --output_file out.wav
          [--noise_scale N] [--length_scale N] [--noise_w N] [--sentence_silence S]
          <  text.txt          # 正文从 stdin 读
```

- **正文走 stdin**。位置参数不是文本；`-t/--text` 这类参数不存在。
- `-m/--model`（`*.onnx`）与 `-c/--config`（`*.onnx.json`）**必须同时给**。
  只给 model 会报找不到 config；config 就是模型 JSON 里那份 `audio` 参数表。
- `-f/--output_file` 指定输出；不指定时它会把 PCM 倒到 stdout（对集成没意义）。
- **`espeak-ng-data/` 必须在 `piper.exe` 旁边**。piper 从**自己 exe 的位置**去找它，
  所以**工作目录可以是任意目录**（实测：`WorkingDirectory` 指向别处也能正常合成）。
  ⇒ 不需要 `cd`、不需要设环境变量；把 zip 解压结果整体保留即可。
- 写入 stdin 后要 **`Close()`**（发送 EOF），否则它会一直等输入。

## 二、多语言 / 多说话人

- 语言由**模型文件**决定，不是参数。英语常用 `en_US-*` / `en_GB-*`。
- 多说话人模型用 `--speaker <id>`；单说话人模型传了会报错。
  模型 JSON 里的 `num_speakers` 能读出说话人数量（= 1 就是单说话人）。
- 采样率读模型 JSON 的 `audio.sample_rate`（`en_US-ljspeech-medium` = **22050**，
  单声道 16 bit）⇒ WAV 头与拼接逻辑都按这个来，别写死 16 kHz。

## 三、长文本实测（关键结论）

| 输入 | 结果 |
|---|---|
| 68 字符单句 | 4.46 s 音频，22,050 Hz / mono / 16-bit / 196,768 B，RTF ≈ **0.07** |
| **7,499 字符（60 句）** | **一次 stdin 输入即正确处理**，输出 **500.6 s** 单文件、22,074,508 B、耗时 **37.8 s** |

**结论**：piper 自身按句切分，**没有实际输入长度上限**，不截断、不乱序。

因此切段策略按"需不需要进度反馈/内存控制"来定，而不是按"有没有上限"：

- 设一个"单趟阈值"（如 4,000 字符）以内直接单趟交给 piper；
- 超过时按**句子边界**切成小段（如 ≤ 2,000 字符），逐段合成后用解码器**按原文顺序**拼回一个 WAV；
- 拼接前**校验各段格式一致**（采样率/声道/位深），否则宁可报错也不要拼出噪声；
- 另设一个**硬上限**（如 20,000 字符）直接拒绝并提示用户拆分。
- 上面三个数字**集中在同一个配置类里**，不要散落在各方法里。

配套的单测要证明切段器**不切断单词、不丢词、不重复**（把各段拼起来应等于规范化后的原文）。

## 四、退出码与常见报错

| 现象 | 原因 |
|---|---|
| 退出码 0 但没有输出文件 | 参数写错/被静默忽略；或正文为空 ⇒ 必须有"产物存在性 + 可解码"的二次校验 |
| 长时间无输出、最后被杀 | 管道缓冲死锁（stdout/stderr 没并发读）或真的超大输入 ⇒ 见 external-cli-integration.md |
| `Unable to find ... espeak-ng-data` | 只搬了 `piper.exe`，没搬整个解压目录 |
| 报找不到 config / `*.onnx.json` | 只给了 `-m` 没给 `-c` |
| 输出是裸 PCM 无头 WAV | 漏了 `-f`，PCM 被倒到了 stdout |
| 中文/非 ASCII 路径失败 | 优先用 ASCII 路径验证；引擎对非 ASCII 支持依版本而定，不要先归因于"编码问题"而绕开 |

## 五、集成侧的最小验收

1. 预检：exe / `.onnx` / `.onnx.json` 三者存在且 JSON 里有 `audio` 节点 ⇒ 得到 `Ready` 状态。
2. 生成：临时文件 → 校验（RIFF 头 + `TotalTime > 0`）→ `File.Move` 到目标名。
3. 回归：断言"时长 > 0""采样率 == 模型 JSON 的 sample_rate""总时长与字符数大致同比例增长"。
4. 失败路径：把 exe 换成不存在 / 换成一个**立刻非零退出**的假程序（例如 Windows 的
   `findstr.exe` 在没给输入时非零退出），断言错误被正确传播成用户可读消息，而不是崩栈。
