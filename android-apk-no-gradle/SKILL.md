---
name: android-apk-no-gradle
description: 不装 Gradle 量产 APK：aapt2→javac→d8→zipalign→apksigner 链路、固定签名可覆盖升级、图标白边、真机 INSTALL_FAILED_ABORTED。
agent_created: true
---

# 免 Gradle 手工构建 APK

目标：一台只装了 Android SDK + JDK 的机器，**不联网、不解析依赖、不下载 Gradle**，
用 SDK 自带的命令行工具产出一个能 `adb install` 的 APK。适用于"只有一个 Activity 的小外壳"。

## 何时用

- 机器上没有 Gradle、也没有 `~/.gradle` 缓存，且不方便下载几百 MB。
- 应用**只用系统 API**（没有 AndroidX / Material / Kotlin / 三方库），依赖集合为空。
- 只想产出一个几十 KB 的 APK 做真机验证，不想为构建系统付成本。

## 六步链路（顺序不能换）

```bash
# 1) 资源 → .flat 包
aapt2 compile --dir res -o build/res.zip

# 2) 链接资源与清单：产出 APK 骨架 + R.java
aapt2 link -o build/base.apk -I $SDK/platforms/android-XX/android.jar \
  --manifest AndroidManifest.xml -R build/res.zip --java build/gen \
  --min-sdk-version 24 --target-sdk-version 36 --auto-add-overlay

# 3) 编译 Java（源码 + 上一步生成的 R.java）
javac -encoding UTF-8 -source 17 -target 17 \
  -classpath $SDK/platforms/android-XX/android.jar -d build/classes <sources...>

# 4) class → dex
java -cp $SDK/build-tools/<ver>/lib/d8.jar com.android.tools.r8.D8 \
  --release --min-api 24 --lib $SDK/platforms/android-XX/android.jar \
  --output build/dex <classes...>

# 5) 把 classes.dex 追加进骨架，再对齐（对齐必须在签名之前）
#    （用 zip 工具追加到 base.apk 的副本，得 unsigned.apk）
zipalign -f 4 build/unsigned.apk build/aligned.apk

# 6) 签名并自检
java -jar $SDK/build-tools/<ver>/lib/apksigner.jar sign \
  --ks keystore/debug.keystore --ks-pass pass:android --key-pass pass:android \
  --ks-key-alias <alias> --v4-signing-enabled false --min-sdk-version 24 \
  --out publisher/App.apk build/aligned.apk
java -jar $SDK/build-tools/<ver>/lib/apksigner.jar verify --print-certs publisher/App.apk
```

## 核心知识点

| 知识点 | 结论 |
|---|---|
| `-I` 就是 android.jar | `aapt2 link` 的 `-I` 与 `javac -classpath` 必须指向**同一个** platform 的 `android.jar`，否则资源 ID 对不上 |
| 版本要对齐 | build-tools 与 platform 版本不一致时的报错很难看懂；先用 `ls` 确认两边都在 |
| JDK 位置 | 优先级：`--jdk` > `JAVA_HOME` > Android Studio 自带 `jbr`（含 javac）> `PATH`。全部落空时给出明确提示，别让它半路失败 |
| `--release` 别误用 | `-source/-target 17` 可用（d8 会 desugar）；若 javac 报 `invalid source release`，降到 8 |
| 签名必须固定 | 换了 keystore，`adb install -r` 会报 `INSTALL_FAILED_UPDATE_INCOMPATIBLE`，只能先卸载（丢数据） |
| `.idsig` 是噪声 | apksigner 默认生成 v4 签名文件（增量安装才用得上）；`--v4-signing-enabled false` 关掉，或构建后删掉，别提交 |
| 图标白边 | 原图本身是「满版方块 + 图形」时，**整图按密度输出**；垫白底再把内容缩到 88% 会在桌面形成一圈白框 |
| 别拆 adaptive icon | 拆成前景/背景层后，背景层缺失或过小必然露出底色；小应用直接给各密度 PNG 最省事 |
| 依赖 | 只有系统 API ⇒ 无依赖解析；一旦引入 AndroidX，这套链路立刻不成立（缺 aar 合并与资源合并） |
| 产物归属 | `publisher/` 提交（可直链下载）；`build/`、`bin/`、`obj/`、`.idsig` 忽略；keystore 视仓库策略（只为可覆盖升级而固定，不放真实凭据） |

## 真机安装的坑

| 现象 | 原因 / 处理 |
|---|---|
| `INSTALL_FAILED_ABORTED: User rejected permissions` | 手机**息屏**时确认弹窗点不了，被系统自动拒绝；`KEYCODE_WAKEUP` 后重试，或连续重试 |
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | 签名变了；卸载重装（先确认数据要不要留） |
| `adb shell ls /sdcard/...` 报本地路径错误 | Git Bash 把 `/sdcard/...` 当成本机路径 ⇒ `MSYS_NO_PATHCONV=1` |
| `adb logcat` 抓不到应用日志 | 部分机型过滤掉；应用自己把日志写进 `files/` 再 `adb shell cat` |
| 桌面图标带白框 | 见上表「图标白边」 |
| 启动即闪退、logcat 有 `NullPointerException` | 常见于在 `setContentView` 之前取 `getWindow().getInsetsController()` |

## 判据

- 判据是**真机三件事**：能装上、能起来、断网时走预期的降级路径。
- 构建脚本要自带 `apksigner verify`，把"签名有效"当作构建成功的一部分。
- 每次改 Java/资源都要重装验证；只改构建脚本参数时，要说明"手机上是哪一版"，别把旧包当新包汇报。

## 参考

- `references/build-chain.md` — 参数逐条说明、目录布局、一次可复用的 Python 编排骨架。
