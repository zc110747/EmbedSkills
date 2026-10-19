# 两端实现骨架与差异

## 1. 桌面端（WinForms + WebView2）

```csharp
// 初始化：显式 user data folder，且注入必须早于第一次 Navigate
var env = await CoreWebView2Environment.CreateAsync(null, cacheFolder);
await webView.EnsureCoreWebView2Async(env);

var core = webView.CoreWebView2;
core.Settings.IsStatusBarEnabled = false;
core.Settings.IsSwipeNavigationEnabled = false;
core.NavigationStarting += (s, e) => _navigating = true;
core.NavigationCompleted += OnNavigationCompleted;   // e.IsSuccess / e.WebErrorStatus
core.WebMessageReceived += OnWebMessageReceived;     // 桥接回传 JSON
core.ProcessFailed += OnProcessFailed;               // 渲染进程崩溃：给提示而不是静默黑屏
core.NewWindowRequested += OnNewWindowRequested;     // 外链交系统浏览器

await core.AddScriptToExecuteOnDocumentCreatedAsync(bridgeScript);  // ← 导航之前
```

**看门狗**（用尝试序号判失效，避免旧计时器误杀新导航）：

```csharp
var attempt = ++_navigationAttempt;
await Task.Delay(TimeSpan.FromSeconds(25));
if (attempt != _navigationAttempt || !_navigating) return;   // 已完成 / 已被新导航取代
_navigating = false;
ShowOffline("连接超时", "…请检查网络后重试。");
```

**自绘界面的离屏渲染**：把 `OnPaint` 抽成 `PaintTo(Graphics, Size)`，既能在窗口里画，
也能在无人值守时 `new Bitmap(w,h)` 里画出来存 PNG —— 启动页/错误菜单就能进自动化。

## 2. Android 端（系统 WebView，无 AndroidX）

```java
WebSettings s = webView.getSettings();
s.setJavaScriptEnabled(true);
s.setDomStorageEnabled(true);     // localStorage 是进度载体，漏开就全丢
s.setDatabaseEnabled(true);
s.setAllowFileAccess(false);      // 只加载线上页面，不需要本地文件
s.setAllowContentAccess(false);
s.setGeolocationEnabled(false);
```

三个必踩的点：

1. **`WindowInsetsController` 在 `setContentView` 之前取会 NPE** —— 那时 DecorView 还是 null。
   要么挪到 `setContentView` 之后，要么用 `getDecorView().getWindowInsetsController()`。
2. **隐藏 WebView 用 `GONE`**。`INVISIBLE` 仍参与合成，渲染表面会盖住启动页 ⇒ 启动一片空白。
3. **`onReceivedError` 只处理主框架**（`request.isForMainFrame()`），子资源 404 不该触发错误菜单。

其它：

- `shouldOverrideUrlLoading`：同 host 返回 `false` 留壳，其它 `startActivity(Intent.ACTION_VIEW)`。
- 返回键：`webView.canGoBack()` → `goBack()`，否则才 `super.onBackPressed()`。
- 导航看门狗用 `Handler.postDelayed`，成功回调里 `removeCallbacks`。
- 桥接用 `addJavascriptInterface(obj, "Native")`（API 17+ 方法必须标 `@JavascriptInterface`）。

## 3. 注入脚本模板（两端共用逻辑，宿主 API 不同）

```js
(function () {
  var KEY = "__STORAGE_KEY__";
  var seed = __SEED__;                       // 进度文件原文；null 表示不覆盖网页数据
  function read() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function post(raw) {                       // 桌面：window.chrome.webview.postMessage
    try { Native.post(raw); } catch (e) {}   // Android：addJavascriptInterface 注入的对象
  }

  // 1) 种子：只在内容不同时写，避免每次启动都触发一次多余写入
  if (typeof seed === "string" && seed.length && read() !== seed) {
    try { localStorage.setItem(KEY, seed); } catch (e) {}
  }

  // 2) 钩子：必须幂等（reload 会重新注入），且写入相同字符串时不重复上报
  var proto = Storage.prototype;
  if (!proto.__bridgeHooked) {
    var native = proto.setItem;
    proto.setItem = function (k, v) {
      native.call(this, k, v);
      if (k === KEY) post(v);
    };
    proto.__bridgeHooked = true;
  }

  // 3) 兜底：DOMContentLoaded / load 各 flush 一次 + 定时轮询
  function flush() { var v = read(); if (v !== null) post(v); }
  document.addEventListener("DOMContentLoaded", flush);
  window.addEventListener("load", flush);
  setInterval(flush, 1500);
})();
```

**注入晚了的补救**（系统 WebView 只能在 `onPageFinished` 注入）：
先探一次存储，为空则写入种子并 **reload 一次**，用一个 `seeded` 布尔守卫防止死循环；
如果注入时发现种子和网页数据不同（说明网页先用旧数据渲染过），同样 reload 一次刷新界面。

## 4. 调试开关（建议固定下来）

```
--self-test                 纯逻辑自检，不开窗口，退出码即结果
--render-preview <dir>      启动页 / 错误菜单离屏渲染 PNG
--capture <png>             导航成功后导出 WebView 画面再退出
FORCE_OFFLINE=1 / --ez force_offline true   强制走错误菜单
<TEMP>/<app>.log            分阶段日志：初始化 / 探网结果 / 导航结果 / 落盘路径
```
