# 环境判定、启动顺序与交付边界

## 1. 先确认浏览器到底能不能用（不要一上来就放弃）

按顺序试，**每步只花几秒**，能过就用真浏览器，别绕：

```bash
# 1) 本机已装的 Edge/Chrome（比下载 Chromium 快得多）
ls "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless=new --no-sandbox \
    --disable-gpu --user-data-dir=/tmp/edgeprof --virtual-time-budget=9000 \
    --dump-dom http://127.0.0.1:<dev_port>/ > /tmp/dom.html; echo "exit=$?"; wc -c /tmp/dom.html
```

**实测（Windows + 受限沙箱）**：`exit=21` 且 `dom.html` **0 字节**、`stderr` 空 —— 说明**沙箱把浏览器
启动拦掉了**，不是参数写错。同样条件下让浏览器自动化工具去 `open` 会**静默挂数分钟**（它内部也要起 Chromium）。
换 `--headless`（旧模式）、加 `--no-sandbox`、改用 PowerShell 工具都**没用**（PowerShell 工具本身还会吞掉子进程输出）。

> 判定口径：**退出码非 0 + 输出为空 + stderr 为空** ⇒ 环境层拦截，别再调参数了，转 Node 侧。
> 若确实必须真浏览器：只能请求放开沙箱权限，而这是要用户点头的操作。

## 2. 启动前端的正确顺序（一次别跳）

```bash
# 1. 后端（后台跑）
cd backend && "$PY" -m <backend_entry> &
# 2. 等端口，别靠 sleep
"$PY" scripts/<wait_for_port>.py 127.0.0.1 <backend_port> 60
# 3. 前端：直接调打包器的 CLI，不经过 npm wrapper、不接管道
cd frontend && "$NODE" node_modules/vite/bin/vite.js --port <dev_port> --strictPort > /tmp/vite.log 2>&1 &
"$PY" scripts/<wait_for_port>.py 127.0.0.1 <dev_port> 90
# 4. 先跑构建（tsc --noEmit && vite build），再跑 Check A / Check B
```

- **`npm run dev` 接 `| tail` 起不来**：实测 npm 生成的 wrapper 一旦接管道，**node 进程都不存在**、
  端口也不监听，而后台任务状态还显示 running。改用上面的直调 CLI 写法，并把日志 `cat` 出来看。
- 构建脚本别写 `tsc -b`：非 composite 工程会出问题。

## 3. CORS：只能靠活服务两端预检

**"读配置核一遍"CORS 是最容易骗过自己也骗过别人的一条**（实测踩到）：白名单**写死**在某个端口、
而启动脚本公布的 `PORT` 变量把页面挪到别的端口时，配置**读起来完全正常**，页面也**能加载**，
但它的每个请求被 **400** 拒（`access-control-allow-origin` 缺失），浏览器把错报成"API 网络错误"。
Check A / Check B 是 **Node 侧**发起请求，**结构上不可能**看见这个故障 —— 全绿与浏览器全挂可以同时为真。

- 白名单必须**按同一个变量派生**（后端每次构造从环境读 `PORT`/`HOST`），别写死；探测地址与绑定地址
  也读**同一个**变量。
- 真要验它，就用**活服务 + 一次预检**，并且**两侧都测**（配置过的 origin 应 200，没配过的 origin 应 400）：

```bash
curl -s -i -X OPTIONS http://127.0.0.1:<backend_port>/api/<route> \
  -H "Origin: http://127.0.0.1:<other_port>" -H "Access-Control-Request-Method: GET" \
  | grep -iE "^HTTP/|^access-control"
```

- **回归测试要写成两侧**：只断言"新 origin 被放行"的话，一个"全放行"的中间件也会让它变绿。
  还有一条更细的：测试若 `import` 了新符号，**旧代码上只会在收集期 `ImportError`** —— 那不算"失败过"，
  要另写一个**只用旧行为**的探针（旧白名单写死在探针自己源码里）跑一次，看它打出缺陷本身。
- 端口是**两端**的：前端 API origin 与后端 `allow_origins` 是两个独立的值，且请求的 Origin 是**页面地址**
  （页面在 `localhost` 而请求发往 `127.0.0.1` 时，两侧都要在名单里）。

## 4. 后台进程与 shell 坑

- **后台进程只活到本次工具调用结束** ⇒ "起服务 → 等就绪 → 跑浏览器脚本 → 清理"必须**写在同一条命令里**。
- **`curl -o /dev/null` 在受限沙箱会被拦**（exit 23，write error）⇒ 落到真实文件再读。
- **写脚本文件不要用 shell heredoc**：`cat > x.mjs <<'JS'` 会报
  `unexpected EOF while looking for matching '`。一律用文件写入工具建文件。
- 生成 GUI/端口的证据时，**端口预检要字段级比较**，别用 `grep ".*:<port>\b"`（某些 grep 版本里
  `\b` 紧跟 `)` 会失效）。

## 5. 交付说明里必须写清的边界

收尾时把下面这段（按实际填）写进 README 或 ADR，**不要只说"验证通过"**：

> `npm run build` 干净；`check_client` N/N（真 client 模块、全部调用、每个面板字段、推导 URL 返回真图）；
> `check_render` N/N（每个面板拿真 payload 渲染，`undefined`/`NaN` 视为失败，含"未连接"空态）。
> **两者都不是浏览器**：effects、socket、CORS 由语言无关客户端与测试套件覆盖。

值得固定成 ADR 的两条**前端契约**（可迁移）：

- **只硬编码 origin**（Vite 的 base 变量），其余 URL 全部从接口公布的 URL 读回 ——
  和"进程外客户端"同一条纪律：前端是另一个进程、另一种语言，写死路由会**静默**失效。
- **没有 API 公布的 URL 要"推导"时，在注释里写清为什么**（例：某类资源 URL 是模板，而该模板只从
  某个汇总端点发出），别让它看起来像随手拼的。

## 6. 收尾清单

- [ ] 构建干净（`tsc --noEmit && vite build`，别用 `tsc -b`）
- [ ] Check A：全部调用打过真服务；**每个面板字段的存在性**单独断言；推导 URL 实打实返回过
- [ ] Check B：每个面板 × { 真 payload, 空 session } 都渲染过；red flag 扫描 + 正样本断言
- [ ] 探针造出的资源全部 `DELETE`（容量常是硬上限，泄漏会留下残渣）
- [ ] 交付说明写明 **L3/L4 没覆盖**
- [ ] 每个面板字段名**对着后端源码核过**，不是凭名字猜的
- [ ] 若启动脚本公布的**端口/主机变量**被改动过，用**活服务预检**验过 CORS：
      配置过的 origin → 200，没配过的 origin → 400（只验前半句会被"全放行"骗过）
