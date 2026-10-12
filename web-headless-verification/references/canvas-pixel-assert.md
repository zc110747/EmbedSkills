# Canvas 2D 像素跨度取证（曲线可见性证明）

用**像素证据**证明「前端一处细微的显示修复真的起作用了」，而不是只截图说"看起来好了"。

核心手法：`canvas.getContext('2d').getImageData()` 扫颜色找曲线像素，量出**曲线的纵向跨度(px)与占画面高度的百分比**，把"看不见 vs 看得见"变成可比的数字（实测：同一段数据 1.3% vs 50.3% = 37.5 倍）。

适用于「波形/曲线/图表改完要证明肉眼可见差异」「缩小量程/加缩放/加高亮后验证」「怎么给视觉修复做受控实验」「截图看着差不多但其实没生效」。

## 核心手法：量曲线的纵向跨度

```js
// 在页面里注入，返回该 canvas 上目标颜色曲线的纵向跨度
window.__probe = () => {
  const c = document.querySelector('.scope-tall canvas');   // 必须限定到某一个 canvas
  if (!c) return null;
  const ctx = c.getContext('2d');
  const w = c.width, h = c.height;                          // 注意 devicePixelRatio
  const d = ctx.getImageData(0, 0, w, h).data;
  let minY = Infinity, maxY = -Infinity, n = 0;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const i = (y * w + x) * 4;
      // 曲线色 #38bdf8 -> 允许容差，避免抗锯齿边缘漏掉
      if (Math.abs(d[i] - 56) < 45 && Math.abs(d[i + 1] - 189) < 45 && Math.abs(d[i + 2] - 248) < 45) {
        n++; if (y < minY) minY = y; if (y > maxY) maxY = y;
      }
    }
  }
  return { w, h, span: n ? maxY - minY : 0, pixels: n };
};
```

判据写成**比例**而不是像素绝对值，才能跨窗口尺寸比较：

```
span / h
```

实测（Python 侧同一次运行、同一段真实数据）：

| 量程模式 | span | 占高度 |
|---|---|---|
| 全局 0–1100 rpm | 4 px | **1.3 %** |
| 偏差 Δ（以目标为零线、对称自适应） | 150 px | **50.3 %** |

→ `37.5 倍`。这就是"看不见 → 看得见"的**可复核证据**。

## 必踩坑 1：对比前先让无关历史滑出缓冲区

前端示波器的缓冲区（ring buffer）里往往还留着**启动斜坡 / 上一次操作**的历史。
若直接对比两种量程：

- 全局量程的 span 会被 **0→满速的加速段**撑满 → 假阳性地"很大"（本次实测得到 88 % span，结论完全无效）。
- 偏差量程也会被同一段历史撑满 → 看起来"没变化"。

**修法**：稳定后**等待超过缓冲区时长**再测量。

```
缓冲区 600 点 @ 50 Hz 推送 → 名义 12 s
实测推送略低于 50 Hz ⇒ 600 点覆盖 > 12 s
⇒ 至少等 16 s，measured settled span 才会归 0
```

判据：**先量一次"稳定态 span"确认 ≈ 0**，再做扰动和对比。这一步不做，后面全是噪声。

## 必踩坑 2：限定 canvas + 容差 + textAlign 残留

- 页面常有多个同色曲线窗（PWM / SPEED / SIGNALS）。`document.querySelector('.scope canvas')`
  会命中第一个 → **读错对象**。要用能唯一命中的选择器（如 `.scope-tall canvas`）。
- 颜色匹配要带容差（`< 45` 量级）。另注意 `ctx.setTransform(dpr, ...)`：
  `canvas.width` 与 `canvas.clientWidth` 不等价，扫描一律用 `canvas.width/height`。
- 若在绘制中改过 `ctx.textAlign`，记得 `save()/restore()`，否则标尺文字会跑到画布外。

## 配套：别把"物理正确"误判成"显示错误"

本次真实案例的顺序值得照抄：

1. 先用**协议层**脚本（Python 直连 WebSocket）扫参数矩阵，断言物理形状：
   `Ki>0 → 跌落→回归`，`Ki=0 → 永久静差 droop = 负载/Kp`（实测 0.05→2.00、0.02→5.00 rad/s，与理论一致）。
   → 结论：**控制器没问题**。
2. 再用**像素层**脚本证明显示端确实把 1 % 的抖动放大成了 50 %。
   → 结论：**问题在量程，不在控制**。

两层分开，才能给出「根因 + 修法 + 可复核证据」，而不是一句"改好了"。

## 自检清单

- [ ] 是否先确认「稳定态 span ≈ 0」，再引入扰动？
- [ ] 等待时间是否**超过缓冲区时长**（而不是"感觉够了"）？
- [ ] 选择器是否唯一命中目标 canvas？
- [ ] 判据是否用 `span / height` 比例而非绝对像素？
- [ ] 是否有**同一段数据**下「修复前 / 修复后」的成对数字？
- [ ] 物理正确性是否已由协议层脚本独立证明（避免把控制问题说成显示问题、或反之）？
