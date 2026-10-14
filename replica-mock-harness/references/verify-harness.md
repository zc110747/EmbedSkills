# 端到端验收脚本契约（verify-harness）

目标：一条命令回答"到底哪些通了"，且结论**可决策、可复现、不会被旧产物骗**。

---

## 一、脚本的六段结构

```
① 前置闸门   —— 产物新鲜度 / 双构存在性 / 替身存在性
② 启动替身   —— 拉起 mock exe，解析 [MOCK] 登记行，拿到桩地址
③ 启动工具   —— 拉起被测工具（带验收参数，非交互模式）
④ 采集输出   —— 分流解析 [MOCK] / [ORACLE] / 工具自身日志
⑤ 逐项核对   —— 三元组比对（工具回读, Oracle, 期望）
⑥ 结论行     —— PASS/FAIL/SKIP 计数 + 一句话结论
```

**顺序不可乱**：闸门必须在任何进程启动之前。
否则你会花 3 分钟等工具跑完，才发现跑的是昨天的 exe。

---

## 二、产物新鲜度闸门（第一优先）

```python
import os, sys, glob

def assert_fresh(product, sources, label):
    if not os.path.exists(product):
        sys.exit(f"[FATAL] {label} 产物不存在: {product}")
    p_mtime = os.path.getmtime(product)
    newest = max((os.path.getmtime(s) for s in sources if os.path.exists(s)),
                 default=0)
    if p_mtime <= newest:
        sys.exit(f"[FATAL] {label} 产物过期：\n"
                 f"  产物 mtime = {p_mtime}\n"
                 f"  最新源码   = {newest}\n"
                 f"  → 先重新构建，本次结论不可信")
    print(f"[GATE] {label} 产物新鲜度 OK")

assert_fresh(EXE_DEBUG,   SRC_ALL, "Debug")
assert_fresh(EXE_RELEASE, SRC_ALL, "Release")
assert_fresh(MOCK_EXE,    MOCK_SRC, "Mock")
```

**为什么必须硬失败**：一旦"跑了旧产物"，所有功能结论都是假的，
而且症状会伪装成"修复无效"，让你回头改已经正确的代码。

---

## 三、启动替身并解析登记

```python
import subprocess, re, time

mock = subprocess.Popen([MOCK_EXE], stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, bufsize=1, text=True,
                        encoding="utf-8", errors="replace")

stubs, aob_addr = {}, None
deadline = time.time() + 10
while time.time() < deadline:
    line = mock.stdout.readline()
    if not line:
        time.sleep(0.05); continue
    m = re.match(r"\[MOCK\] (\w+) addr=0x([0-9A-Fa-f]+)", line)
    if m:
        stubs[m.group(1)] = int(m.group(2), 16)
    m = re.match(r"\[MOCK\] aob_stub @0x([0-9A-Fa-f]+)", line)
    if m:
        aob_addr = int(m.group(1), 16)
    if "[MOCK] ready" in line:
        break
else:
    mock.kill()
    sys.exit("[FATAL] 替身启动超时 / 未打印 ready")
```

**要点**：
- 用前缀 + 正则解析，**不要依赖固定行号**
- 必须有 ready 信号 + 超时兜底，否则替身崩了脚本会挂死
- `errors="replace"` 防止编码异常中断整个采集

---

## 四、控制台编码处理

Windows 下工具的 stdout 编码与 Python 默认解码常常不一致，
会出现乱码或 `UnicodeDecodeError` 直接终止脚本。

**三种处理，按可靠性排序**：

```python
# 方案 1（推荐）：显式指定编码 + 容错
subprocess.Popen(..., text=True, encoding="utf-8", errors="replace")

# 方案 2：捕获字节后自行解码
raw = proc.stdout.read()
text = raw.decode("utf-8", errors="replace")

# 方案 3：让被调程序主动设编码（C# 侧）
#   Console.OutputEncoding = System.Text.Encoding.UTF8;
```

**反模式**：用 `chcp 65001` 依赖外部环境 —— 脚本换个终端就崩。

---

## 五、采集与分流

```python
tool_log, oracle = [], []
for line in tool.stdout:
    tool_log.append(line.rstrip())
    if line.startswith("[ORACLE]"):
        oracle.append(parse_oracle(line))
```

**分流原则**：
- 工具自己的报告行 → 用于核对写入/回读
- `[ORACLE]` 行 → 用于交叉核对
- `[MOCK]` 行 → 只用于启动期登记

**不要**把三类混在一个 buffer 里 —— 解析逻辑会互相污染。

---

## 六、逐行判据记录

每项记录一条结构化结果，**必须含错误文本**：

```python
rows = []   # (verdict, name, kind, detail)

def Check(ok, name, kind, detail):
    rows.append(("PASS" if ok else "FAIL", name, kind, detail))

def Skip(name, detail):
    rows.append(("SKIP", name, "skip", detail))
```

调用侧：

```python
Check(on and off, flag, "codehook",
      f"{probe.Text} | on:{onMsg} | off:{offMsg}")
```

`detail` 是排查的唯一线索 —— 写"失败"两个字等于没写。

---

## 七、结论行（人工唯一入口）

```python
n_pass = sum(1 for r in rows if r[0] == "PASS")
n_fail = sum(1 for r in rows if r[0] == "FAIL")
n_skip = sum(1 for r in rows if r[0] == "SKIP")

print("=" * 64)
print(f" PASS = {n_pass}    FAIL = {n_fail}    SKIP = {n_skip}")
print(f" 交叉核对 (Oracle) : {oracle_ok}/{oracle_total} 一致")
print(f" 结论: {'PASS' if n_fail == 0 else 'FAIL'}")
print("=" * 64)

sys.exit(0 if n_fail == 0 else 1)
```

**退出码必须反映结论** —— 这样才能接进 CI / 批处理。
`FAIL>0 → exit 1`，`FAIL==0 → exit 0`（SKIP 不影响退出码，
因为 SKIP 是**环境属性**，不是缺陷）。

---

## 八、SKIP 的分类汇总

```python
skip_a = [r for r in rows if r[0] == "SKIP" and "代码位点" not in r[3]]
skip_b = [r for r in rows if r[0] == "SKIP" and "代码位点" in r[3]]

if skip_a:
    print(f" SKIP {len(skip_a)} 项为无运行期数据源者（需自研代码钩子，"
          f"见 docs/TGA_ADAPTATION.md §5 B3）")
if skip_b:
    print(f" SKIP {len(skip_b)} 项为代码钩子类：替身未布该位点（无钩子桩），"
          f"位点存在性与 arm/disarm 还原需在真机验证")
```

**这一段是给读报告的人做决策用的** ——
它回答"这些没验的项，我下一步该在真机上做什么"。

---

## 九、超时与清理

```python
try:
    run_all()
finally:
    for p in (tool, mock):
        try:
            p.terminate()
            p.wait(timeout=5)
        except Exception:
            p.kill()      # 兜底
```

**要点**：
- `finally` 里清理，保证工具崩了也不留僵尸进程
- 工具侧要有总超时（脚本级 + 工具内部双重）
- 工具崩溃 vs "没接上"要能区分：崩溃时退出码异常 / 无报告段

**坑**：被测工具被占用时清理会失败 —— 加 `kill()` 兜底。

---

## 十、干跑启动器（`--dry-run`）

加一个只打印不执行的模式，用于**先验参数契约**：

```python
if "--dry-run" in sys.argv:
    print("[DRY-RUN] 将被验证的项目:")
    for f in all_flags:
        print(f"  - {f.name:24s} kind={f.kind:9s} "
              f"{'[需桩]' if f.needs_stub else ''}")
    print(f"[DRY-RUN] 替身桩清单: {len(stubs)} 条")
    print("[DRY-RUN] 不会启动任何进程")
    sys.exit(0)
```

**价值**：
- 5 秒内发现"参数名写错 / flag 拼错 / 桩清单为空"
- 不用等 3 分钟的完整跑
- 也是给用户的**文档**：一眼看清验收集合

---

## 十一、双构验收

Debug 与 Release **都要跑**（至少都要构建通过）：

```bash
# Debug
dotnet build -c Debug   /p:TreatWarningsAsErrors=false
python tools/verify_features.py --exe build/Debug/tool.exe

# Release
dotnet build -c Release
python tools/verify_features.py --exe build/Release/tool.exe
```

**为什么**：优化器差异会暴露 `volatile` 缺失、只写不读的桩、
以及"Debug 下能跑、Release 下被优化掉"的接线。

**零警告是硬要求** —— 警告里常藏着"未使用变量"（= 桩被优化掉的信号）
或"类型不匹配"（= 位域写入长度错的信号）。

---

## 十二、脚本自身的常见坑

| 坑 | 症状 | 修法 |
|---|---|---|
| 不查 mtime | 反复跑旧产物，误判"无效" | 第一段加新鲜度闸门 |
| 依赖固定行号 | 日志一改脚本就崩 | 前缀 + 正则解析 |
| 编码未指定 | 乱码 / 异常终止 | `encoding="utf-8", errors="replace"` |
| 无超时 | 工具挂死，脚本跟着挂 | 总超时 + ready 信号 |
| 清理不在 finally | 残留僵尸进程占端口/文件 | `finally` 里 terminate + kill |
| 退出码恒 0 | 无法接 CI | `exit(0 if fail==0 else 1)` |
| 只打印计数不打印明细 | 无法定位 | 明细行必须带错误文本 |
| 没有 dry-run | 参数错了要等 3 分钟才发现 | 加 `--dry-run` |
| 断言写死数量 | 需求一改脚本就假 FAIL | 断言"集合内容"，不断言"条数"（或明确注释条数来源） |
| 探针过期未同步 | 需求变更后断言失效报假 FAIL | 需求变更后**同步更新探针判据** |

> 最后一条是本类工作中最高频的自伤：
> **产品改了，探针没改**，于是探针报 FAIL，你去改正确的产品。
> 每次需求变更后，第一件事是问"有哪些断言依赖旧行为"。

---

## 十三、脚本产物落盘

验收脚本应把关键证据落盘，供事后复核：

```
docs/recon/
├── ui_after_left_panel_edit.png     截图证据
├── verify_features_2026-10-14.log   验收原始日志
└── oracle_changes_2026-10-14.log    替身 change 日志
```

**价值**：结论可追溯。别人质疑"真的通了吗"，你甩日志而不是复述。
