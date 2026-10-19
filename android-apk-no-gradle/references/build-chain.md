# 构建链参数与工程布局

## 1. 最小工程布局（无 Gradle）

```
android/
├── AndroidManifest.xml
├── res/
│   ├── values/{strings.xml, colors.xml, styles.xml}
│   └── mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png
├── src/main/java/<pkg>/…
├── keystore/debug.keystore          # 固定签名，才能 adb install -r 覆盖升级
├── tools/build_apk.py               # 编排（标准库即可）
└── publisher/App.apk                # 产物
```

图标尺寸：mdpi 48 / hdpi 72 / xhdpi 96 / xxhdpi 144 / xxxhdpi 192 px。
**不要**建 `mipmap-anydpi-v26/ic_launcher.xml`（adaptive icon）除非确实准备了两层素材。

`AndroidManifest.xml` 要点：

```xml
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="com.example.app"                    <!-- aapt2 link 需要，别漏 -->
    android:versionCode="1" android:versionName="1.0.0">
  <uses-permission android:name="android.permission.INTERNET"/>
  <application android:label="@string/app_name" android:icon="@mipmap/ic_launcher"
               android:theme="@style/AppTheme" android:usesCleartextTraffic="true">
    <activity android:name=".MainActivity" android:exported="true">
      <intent-filter>
        <action android:name="android.intent.action.MAIN"/>
        <category android:name="android.intent.category.LAUNCHER"/>
      </intent-filter>
    </activity>
  </application>
</manifest>
```

`styles.xml` 用平台主题即可（不需要 Material 库）：
`<style name="AppTheme" parent="android:Theme.Material.Light.NoActionBar"/>`

## 2. 各步参数

| 步骤 | 关键参数 | 说明 |
|---|---|---|
| `aapt2 compile` | `--dir res -o build/res.zip` | 整个 res 目录一次编译 |
| `aapt2 link` | `-o build/base.apk -I <android.jar> --manifest … -R build/res.zip --java build/gen --min-sdk-version … --target-sdk-version … --auto-add-overlay` | 产出 APK 骨架 + `R.java`（后者要和源码一起 javac） |
| `javac` | `-encoding UTF-8 -source 17 -target 17 -classpath <android.jar> -d build/classes` | 源文件列表 = `src/**/*.java` + `build/gen/**/*.java` |
| `d8` | `--release --min-api <minSdk> --lib <android.jar> --output build/dex` | 输入是所有 `.class`（**不是** jar） |
| 追加 dex | zip 追加 `classes.dex` 到骨架副本 | `arcname` 必须是根目录 `classes.dex`；先 `shutil.copyfile` 再 `ZipFile(..., "a")` |
| `zipalign` | `-f 4 unsigned.apk aligned.apk` | **必须在 apksigner 之前**；事后对齐会破坏签名 |
| `apksigner sign` | `--ks … --ks-pass pass:… --key-pass pass:… --ks-key-alias … --v4-signing-enabled false --min-sdk-version … --out …` | `--v4-signing-enabled false` 避免多出 `.idsig` |
| `apksigner verify` | `--print-certs` | 输出签名者证书，作为构建成功的最后一道断言 |

排查用：

```bash
aapt2 dump badging publisher/App.apk     # 看 label / versionCode / minSdk / targetSdk / launcher
unzip -l publisher/App.apk               # 确认 classes.dex 在根目录、res 已编入
```

## 3. Python 编排骨架（只用标准库）

```python
def resolve_sdk() -> Path:          # --sdk > ANDROID_SDK_ROOT > 常见安装位置
def resolve_jdk() -> Path:          # --jdk > JAVA_HOME > Studio jbr > PATH 里的 javac
def build_tools(sdk) -> Path:       # 取 build-tools 下最大的版本目录
def platform(sdk) -> Path:          # 取 platforms 下最大的 android-XX，拿 android.jar
def run(cmd, label):                # subprocess.run(check=True)，失败打印完整命令行
```

要点：

- 每一步打印 `== n/6 步骤名 ==`，失败时能一眼看出断在哪一步。
- 工作目录（`build/`）每次构建前清空；产物目录保留。
- keystore 不存在时用 `keytool -genkeypair` 生成（`-keyalg RSA -keysize 2048 -validity 10000`），
  口令用调试签名的惯例值即可 —— **不放任何真实凭据**。
- 退出码统一：`0` 成功，非 0 带一句人能读的原因。
