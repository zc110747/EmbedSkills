# 移动端布局与「改了没生效」

## 1. 竖排容器里的 `flex-basis` 会跑去量高度

```css
/* 出问题：横向看着完全正常 */
.nav-link { flex: 1 1 200px; }

@media (max-width: 640px) {
  .continue-nav { flex-direction: column; }   /* 容器翻成竖排 */
}
```

症状：桌面端正常，**移动端每个卡片被撑成 200px 高**（看起来"标签太大了"），
而且改 `padding` / `height` 都没用 —— 因为撑开它的是 `flex-basis`，不是内容。

根因：`flex-basis` 跟随主轴。主轴变成 `column` 后，`200px` 就从"最小宽度"变成"高度"。

```css
/* 正确：基准写 0，最小尺寸交给 min-width */
.nav-link { flex: 1 1 0; min-width: 200px; }
```

- 横向逐像素不变（`flex-grow` 平分剩余空间，`min-width` 兜底），
  竖排时 `min-height` 保持默认 `auto`，高度回到内容高度。
- 通用规则：**`flex-basis` 不要写 `px`**；`%` 和 `auto` 不会在换轴后变成错误语义。
- 修法放**共享规则层**，别用媒体查询打补丁 —— 补丁存在时，一旦样式表被缓存，
  你会同时怀疑"补丁写错"和"缓存没刷"，排查成本翻倍。

## 2. 量尺寸而不是看截图

```js
// headless chromium：多种视口逐个量，取真实几何而不是肉眼
const m = await page.evaluate(() => {
  const nav = document.querySelector('.continue-nav');
  const card = document.querySelector('.nav-link');
  const r = card.getBoundingClientRect();
  return { dir: getComputedStyle(nav).flexDirection,
           w: Math.round(r.width), h: Math.round(r.height) };
});
```

- 判据：`dir === 'column'` 时每张卡高度应等于内容高度（例：52.6 px），不是 `flex-basis` 的值。
- 改动前后在 **641 / 700 / 900 px** 也各量一次，确认"只是修了竖排、横向没动"。
- 顺带看 `document.documentElement.scrollWidth > innerWidth` 判横向溢出。

## 3. 线上仍显示旧样子：三步定位

1. **部署物**：远端分支与 HEAD 齐平？线上文件字节数 == 本地字节数？
2. **缓存**：`curl -D - <url> -o /dev/null` 看 `Last-Modified` 与 `Cache-Control: max-age=600`，
   再对用户反馈的时间点 —— 页面比部署时间早，就是缓存，不是代码。
3. **代码**：对**线上真实 URL** 跑 headless 量一遍（别对本地文件量，那证明不了部署）。

结论落到工程上：所有 CSS/JS 的 URL 挂内容指纹（`?v=<sha256 前 8 位>`），内容一变 URL 必变。
