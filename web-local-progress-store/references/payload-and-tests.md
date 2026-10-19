# 载荷字节形态、校验清单与测试配方

## 1. 导出载荷（对外契约）

```json
{
  "schemaVersion": 1,
  "completedArticles": [
    "0001",
    "0002"
  ],
  "updatedAt": "2026-10-19T01:42:10.526Z",
  "exportedAt": "2026-10-19T01:42:10.528Z"
}
```

- 生成方式：`JSON.stringify(payload, null, 2)` —— **2 空格缩进**，数组元素各占一行，**键序固定**。
- 行尾 **LF**，**结尾换行**（`json.dumps(..., indent=2) + "\n"` 同理）。
- 时间戳：ISO 8601 UTC，带毫秒（`…T01:42:10.526Z`）。`updatedAt` 是最后一次改动，`exportedAt` 是导出时刻。
- 文件名：`<app>-progress-YYYYMMDD.json`（日期取本地导出日）。
- 浏览器侧下载：`new Blob([text], {type: "application/json"})` + `<a download>` + `URL.revokeObjectURL()`。
- 其它语言复刻时**逐字节对齐**这五点（缩进 / 行序 / 键序 / 行尾 / 结尾换行），否则"可互相导入"是假的。

## 2. 导入校验清单（按顺序，任一步失败就停并说明）

| 步 | 检查 | 失败处理 |
|---|---|---|
| 1 | 文件能读成 UTF-8 文本 | 提示"不是文本文件" |
| 2 | `JSON.parse` 成功 | 提示"不是合法 JSON" |
| 3 | 顶层是对象 | 提示"结构不对" |
| 4 | `schemaVersion` 存在且在支持列表 | 提示"版本不支持"（不尝试兼容） |
| 5 | 条目字段是数组，元素是字符串 | 提示"结构不对" |
| 6 | ID 形状合法（如 `^\d{4,}$`，四位补零、超四位不截断） | 非法条目**跳过并计数** |
| 7 | 去重 | 静默去重 |
| 8 | 与当前数据取交集/差集，未知 ID **计数** | 允许导入，提示"忽略 N 条本项目不存在的编号" |
| 9 | 有效条目为 0 | 拒绝，"没有任何可导入的记录"，现有数据不动 |

预览要同时给出：文件有效条数、当前条数、**合并后条数**、**覆盖后条数** —— 用户按数字选模式，而不是按文字猜。

## 3. 测试配方

**纯逻辑（Node）**：模块顶层不碰 `document`，纯函数挂到 `globalThis`。
用一份假存储（内存对象）跑：编号补零、非法条目计数、去重、未知 ID 忽略、合并并集、
除零保护、导出载荷键序与文件名、**导出内容能被导入解析器读回**（round-trip）。

**真实 DOM（jsdom）**：

```js
const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://localhost/" });
// runScripts 必须是 "outside-only"：缺了它 window.eval 静默不执行，用例会"通过"但没有行为
await new Promise(r => dom.window.addEventListener("load", r));  // defer 脚本先于 load 执行完
```

- 断言 `aria-expanded` / `dialog.open` / `aria-pressed` 这类**属性**，不断言视觉。
- ⚠️ **jsdom 可能被环境清掉**：`require('jsdom')` 失败时若用 `test.skip`，整组 DOM 用例会集体跳过，
  而测试框架仍报"全绿"。所以必须盯 **skipped 数量**（例：应为 `155 passed`，出现 `14 skipped` 就是环境缺包）。
  修复：`npm install jsdom`（装到运行测试的那个 node_modules）后重跑。

**跨端一致性**：把两端写出的文件直接按字节比对；至少断言 `\r\n` 计数与结尾字节。
