# Check B：把每个组件拿真 payload 渲染一遍

## 原理

`react-dom/server` 的 `renderToStaticMarkup` **只要 DOM 树、不要 DOM**，所以能在 Node 里跑。
**判据不是"渲染不崩"，而是输出里不许出现 `undefined` / `NaN` / `[object Object]`。**

```js
const RED_FLAGS = ["undefined", "NaN", "[object Object]", "Infinity"];
for (const [name, html] of renders) {
  const found = RED_FLAGS.filter((flag) => html.includes(flag));
  report(`${name} shows no undefined/NaN`, found.length === 0, found.join(", ") || "clean");
}
```

## 必须额外做的两件事（否则这个 check 会自我欺骗）

1. **每个面板都要用"什么都没接上"的空 session 再渲一遍。**
   每个面板常有一个 `if (!data) return ...` 的提前返回，那里漏个 `?` 就是**白屏**——
   而用户对白屏的唯一解读是"前端坏了"。
2. **正样本断言**：光"没有 red flag"是可以通过"什么都没渲出来"的。再断言几个**必须出现**的东西：

```js
report("the panel shows every item name",
       snapshot.items.every((it) => html.includes(it.name)));
report("the panel shows every visited phase",
       run.status.phase_log.every((e) => html.includes(e.phase)));
```

正样本的锚点应选**从活 payload 里现取的字符串**（名字、阶段、计数），不要选探针自己拼的常量。

## 组件渲染的坑

**`Invalid hook call ... Cannot read properties of null (reading 'useState')`**
= **把组件当普通函数调了**（`Panel({session})`），跑在 React renderer 之外。
修法：entry 里导出 `renderPanel(name, props)`，内部走 **`createElement`** 建立元素，
再交给 `renderToStaticMarkup`。

其余打包类坑（CJS 格式、`import.meta` 替换、产物写成文件、`nodePaths`、`.css` loader）见 `esbuild-probe.md`。

## 边界

组件渲染覆盖不到 effects、fetch 接线、轮询、socket —— 那些要真浏览器，
或把 effect 里的纯逻辑手动搬到 Check A 的 Node 环境里测。
