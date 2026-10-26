# Check A：用客户端自己的模块打活服务

## 为什么不能用重写的调用逻辑

**不要重写一遍调用逻辑，把前端 client 模块本身打出来跑。** 重写就变成"测我的测试"，而 bug 就住在那份模块里。
同理，**payload 从活服务现取**，手写 fixture 会照着"我以为的形状"写。

## 探针骨架

借用**前端自己的 `node_modules`**（探针自己装一份依赖会引入版本漂移）：

```js
import { createRequire } from "node:module";
import path from "node:path";

const frontend = path.resolve(here, "..", "frontend");     // 前端工程根
const require = createRequire(path.join(frontend, "package.json"));
const esbuild = require("esbuild");

const built = await esbuild.build({
  entryPoints: [path.join(frontend, "src", "api", "client.ts")],
  bundle: true, format: "cjs", write: false, platform: "node",
  // 打包器（如 Vite）在构建期替换 import.meta.env；探针必须做同样的替换，
  // 否则模块一加载就崩。只硬编码 origin，其余 URL 从接口读回。
  define: { "import.meta.env.<BASE_VAR>": JSON.stringify(backendOrigin) },
});
```

产物**写成文件**再 `require`，不要走 `await import("data:text/javascript;base64,...")`：

```js
// outfile: path.join(tmpdir, "client.cjs")
const mod = require(outfile);
```

## 字段存在性断言（核心判据）

```js
const missing = (object, paths) => paths.filter((dotted) => {
  let value = object;
  for (const key of dotted.split(".")) value = value?.[key];
  return value === undefined;          // ← 判据是"字段在不在"，不是"抛不抛异常"
});

const miss = missing(payload, ["meta.count", "list.items", "config.limits", "streams"]);
check("every field the panels read exists", miss.length === 0, miss.join(", ") || "none missing");
```

路径列表 = **面板真正读的每一个字段**，必须对着后端源码核过，不能凭名字猜。

顺手也要验**推导出来的 URL**：打一次，看返回的 content-type / 内容是不是预期，
别只比字符串是否相等。

## 实测抓到的两类"编译器看不见"的 bug

1. **计数对象的字段名与类型声明不符**：wire 上是 `{a, b, c}` 三元组，类型声明里写的是另一个名字
   （如 `capacity`），面板渲染成 `1 live of undefined`。TS 编译通过。
2. **类型声明里的字段在 wire 上不存在**：服务端把它做成 `@property`（不进 JSON），真实传输的是
   若干**并行数组**。读它编译通过、运行时是 `undefined`。

两者都是"字段名对不上"这一高频 bug 的形态，只有存在性断言能抓到。

## 打包与加载的坑

| # | 症状 | 原因 | 修法 |
|---|---|---|---|
| 1 | `Error: Dynamic require of "stream" is not supported` | `react-dom/server` 是 Node 构建、内部 `require("stream")`；**ESM 打包会把 require 干掉** | esbuild 用 **`format: "cjs"`**，配 `createRequire` 加载产物 |
| 2 | `Cannot read properties of undefined (reading '<BASE_VAR>')` | CJS 下 `import.meta` 为空 | build 时 `define: {"import.meta.env.X": JSON.stringify(url)}` |
| 4 | 报错信息里塞了几 MB 的 base64 | `import("data:text/javascript;base64,...")` 失败时整个 URL 进了异常消息 | 产物写 `outfile`，再 `createRequire(import.meta.url)(outfile)` |
| 5 | `Could not resolve "react"` | esbuild 工作目录不在前端里，找不到前端的 `node_modules` | `nodePaths: [path.join(frontend, "node_modules")]` **且** entry 里用**绝对路径** import 各组件 |
| 6 | `.css` 导入报错 | 组件或其入口 import 了样式 | `loader: { ".css": "empty" }` |

坑 3（`Invalid hook call`）见 `ssr-render-probe.md`。

## 边界

Check A 是 **Node 侧**发起请求，**结构上不可能**看见 CORS 故障：全绿与浏览器全挂可以同时为真。
effects / 轮询 / socket 同样不覆盖。
