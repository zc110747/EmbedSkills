---
name: win-gui-screenshot-verify
description: Windows桌面GUI(SDL/LVGL/Qt)零依赖自动化视觉验收:ctypes+BitBlt抓客户区、DPI感知点击、纯Python PNG裁剪放大、单调用编排。触发:GUI截图、自动化验收、点击没反应、DPI缩放、BitBlt黑屏。
agent_created: true
---
# Windows GUI 的零依赖自动化视觉验收（完整配方 · 由 win-gui-screenshot-verify 并入）

## 一、何时用本 skill

- 要**自动验证一个 Windows 桌面 GUI**（自绘界面尤其需要截图，因为没有可断言的控件树）。
- 手上**没有 Pillow / numpy / pyautogui**，也不方便装（离线、内网、npm/pip 受限）。
- 合成鼠标点击**没反应**，或"点到了别的地方"。
- 截图**拍到的是 IDE / 黑屏**，不是目标窗口。
- 需要把截图**放大看细节**（"这个字是不是被裁了"）。

---

## 二、截图：BitBlt 抓客户区

```python
u32 = ctypes.WinDLL("user32", use_last_error=True)
gdi = ctypes.WinDLL("gdi32", use_last_error=True)

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def capture(out_png, title):
    hwnd = u32.FindWindowW(None, title)
    if not hwnd:
        raise SystemExit("WINDOW_NOT_FOUND")
    # 关键：BitBlt 读的是"合成后的桌面"，被遮挡就会拍到压在它上面的窗口
    u32.ShowWindow(hwnd, 9)          # SW_RESTORE
    u32.SetForegroundWindow(hwnd)
    u32.BringWindowToTop(hwnd)
    time.sleep(0.5)

    client = RECT(); u32.GetClientRect(hwnd, ctypes.byref(client))
    origin = POINT(0, 0); u32.ClientToScreen(hwnd, ctypes.byref(origin))
    w, h = client.right, client.bottom

    src = u32.GetDC(None)                       # 整个屏幕 DC
    mem = gdi.CreateCompatibleDC(src)
    info = BITMAPINFO()                          # biHeight 取负 = 自上而下
    info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = w
    info.bmiHeader.biHeight = -h
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0             # BI_RGB
    bits = ctypes.c_void_p()
    bmp = gdi.CreateDIBSection(src, ctypes.byref(info), 0,
                               ctypes.byref(bits), None, 0)
    gdi.SelectObject(mem, bmp)
    gdi.BitBlt(mem, 0, 0, w, h, src, origin.x, origin.y, 0x00CC0020)  # SRCCOPY
    buf = ctypes.string_at(bits, w * h * 4)      # BGRA，写 PNG 时换序
    ...
```

要点：
- **只抓客户区**（`GetClientRect` + `ClientToScreen`），不要连标题栏一起抓，
  否则后面按 UI 坐标点算的偏移会差一个标题栏高度。
- `biHeight` 用**负数**得到自上而下的行序，省一次翻转。
- 抓之前 `ShowWindow(SW_RESTORE)` + `SetForegroundWindow` + `BringWindowToTop`
  —— 少了这一步，"截图抓到 IDE"是最常见的结果。

---

## 三、点击：DPI 感知 + 真实输入

### 3.1 先解决 DPI：逻辑坐标 ≠ 物理像素

Windows 缩放 150% 时，一个"逻辑 800x480"的窗口客户区是 1200x720 物理像素。
`SetCursorPos` 收的是**物理**像素，于是所有点击都偏 1.5 倍。

```python
try:
    u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
except Exception:
    u32.SetProcessDPIAware()
```

然后**从客户区宽度反推比例**，不要写死：

```python
rect = RECT(); u32.GetClientRect(hwnd, ctypes.byref(rect))
scale = rect.right / LOGICAL_WIDTH          # 物理像素 / UI 逻辑像素
px, py = int(lx * scale), int(ly * scale)
origin = POINT(0, 0); u32.ClientToScreen(hwnd, ctypes.byref(origin))
sx, sy = origin.x + px, origin.y + py
```

### 3.2 用真实输入，不要 PostMessage

**SDL2 会忽略它没看到到达鼠标焦点的投递消息**（`PostMessage(WM_LBUTTONDOWN)` 无效）。
必须注入真实输入：

```python
u32.ShowWindow(hwnd, 9); u32.SetForegroundWindow(hwnd); time.sleep(0.5)
u32.SetCursorPos(sx, sy); time.sleep(0.3)
u32.mouse_event(0x0002, 0, 0, 0, None)   # LEFTDOWN
time.sleep(0.12)
u32.mouse_event(0x0004, 0, 0, 0, None)   # LEFTUP
```

`mouse_event` 是合成输入，**用户会看到鼠标真的动**。这一点务必提前告知使用者。

### 3.3 算坐标只看物理像素，别看"显示器里的观感"

踩过的坑：把**展示给我看的缩放图**里的像素当成物理像素，算出来的按钮坐标偏了
整整 75px，点了空白处。正确做法：
- 客户区物理尺寸 = `GetClientRect` → 除以逻辑宽度得到 scale；
- 或者直接用 `crop.py` 裁一块目标区域出来，**在裁剪图上量**，再换算回物理坐标。

---

## 四、看图：纯 Python PNG 裁剪 / 放大 / BMP 转换

没有 Pillow 也能读 PNG（`struct` + `zlib`，支持 8-bit、filter 0–4、
灰度/RGB/RGBA）然后做最近邻放大：

```python
# 解码：逐行解 filter（0 None / 1 Sub / 2 Up / 3 Average / 4 Paeth），再存成 RGB
# 放大：out[(oy*ow+ox)*3:...] = rgb[((y+oy//scale)*w + (x+ox//scale))*3 : ...]
# 编码：每行前置 filter byte 0，zlib.compress，再按 (len,tag,payload,crc32) 拼块
```

用途：
- **放大 4–8 倍**确认"字符是不是被右边缘裁掉了"（肉眼看缩略图永远说不准）。
- 从**任意 PNG**里裁任意矩形（包括用户粘贴的截图），验证问题而不必重新跑程序。
- 把程序输出的 **24bpp BMP 转 PNG**（`Read` 工具显示不了 BMP）：
  读 `bfOffBits`(偏移 10)、宽高(18/22)、`biBitCount`(28)，行按
  `(w*3+3)//4*4` 对齐且**自下而上**，写成 PNG 前翻一次行序。

---

## 五、编排：一条命令内跑完，别用跨调用的后台进程

沙箱/CI 环境下**上一次工具调用里 `(cmd &)` 起的后台进程，下次调用就没了**：

```
# ❌ 分两次调用
bash# ./app.exe & sleep 10        # 返回
bash# python click.py 137 96      # WINDOW_NOT_FOUND —— 进程已被回收
```

```bash
# ✅ 一次调用里串起来；先 taskkill 清残留，再启动、等、点、截
MSYS2_ARG_CONV_EXCL='*' taskkill /F /IM app.exe >/dev/null 2>&1; sleep 1
(cd bin && ./app.exe --log-level debug > ../logs/run.log 2>&1 &) \
  && sleep 12 \
  && python tools/click.py 137 96 && sleep 3 \
  && python tools/shot.py logs/main.png \
  && python tools/click.py 748 317 && sleep 25 \
  && python tools/shot.py logs/detail.png
```

- 启动等待给足（SDL/LVGL 初始化 + 首轮网络请求，12s 起）。
- **合成点击可能触发额外导航**（例如"整条页头可点"），截详情页要在点击后
  **立刻**截，别等太久。
- `MSYS2_ARG_CONV_EXCL='*'` 防止 Git Bash 把 `/F` 当路径改写。
- 日志用 `grep -E "TAG\]"` 抽指定模块，比 `tail -50` 可靠。

---

## 六、验证输出该长什么样

一次合格的 GUI 验收至少包含：

| 项 | 证据 |
|---|---|
| 进程真的起来了 | 启动日志关键行（后端就绪、监听端口、进入主循环）|
| 界面渲染正确 | 主界面截图 + 目标区域**放大图** |
| 交互链路通 | 点击后的事件日志（`opened detail page` / `manual refresh requested`）|
| 异步结果落地 | 请求耗时与返回长度日志 + 结果落地后的截图 |
| 没有退化 | 长跑若干秒后有意义的告警计数（应为 0）|

**不要只凭"日志看起来对"就宣布通过** —— 自绘界面里"日志正常 + 界面全错"
是常态（见 `lvgl-mcu` 里的字形覆盖故障）。
