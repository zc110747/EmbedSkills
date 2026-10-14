# Oracle 交叉核对与判据分类（oracle-and-verdicts）

目标：把"验证通过"从**单一证据**升级为**交叉核对**，并把 PASS/FAIL/SKIP 的语义钉死。

---

## 一、为什么需要 Oracle

工具侧的验证逻辑是：

```
写值 → ReadProcessMemory 回读 → 回读 == 期望 → 报 PASS
```

**这条链有一个致命漏洞**：如果工具其实写到了自己的缓冲（没真写进目标进程），
或者回读逻辑读的也是自己的缓冲，那它**照样报 PASS**。

所以必须有一条**独立于工具**的证据链。这就是 Oracle。

### 两条证据链

| 链 | 来源 | 能证明什么 |
|---|---|---|
| 链 A：工具回读 | 被测工具 | 工具自己的读写闭环自洽 |
| 链 B：替身采样 | 替身进程自身 | **目标进程里的值真的变了** |

**只有 A ∧ B 同时成立，才叫"真的写进去了"。**

---

## 二、Oracle 的实现（替身侧）

替身主循环里周期性采样并打印：

```c
static void oracle_sample(uint32_t t_ms) {
    printf("[ORACLE] t=%.2fs hp=%d stamina=%.1f souls=%d flags=0x%02X\n",
           t_ms / 1000.0,
           g_data.hp, g_data.stamina, g_data.souls, g_data.flags);
}
```

采样频率建议 **200~500ms**：
- 太快 → 日志爆炸，解析慢
- 太慢 → 漏掉工具的瞬时写入（写完立刻被工具还原的场景）

**必须 `fflush(stdout)`** —— 否则管道缓冲导致采样丢失，
你会看到"工具说写了、Oracle 没记录"的假不一致。

### change 日志（值变化时才打印）

```c
static int32_t last_hp = -1;
if (g_data.hp != last_hp) {
    printf("[ORACLE][CHANGE] hp %d -> %d @t=%.2fs\n",
           last_hp, g_data.hp, t_ms / 1000.0);
    last_hp = g_data.hp;
}
```

**change 日志的价值**：它是一条**时间戳证据**，
能证明"工具在 t=1.2s 写的值"与"替身在 t=1.2s 观测到的变化"是同一件事。
周期采样只能证明"某时刻值是这样"，change 日志能证明"**是谁写的、什么时候**"。

---

## 三、交叉核对的三元组

每一项记录三元组：

```
(工具回读值, 替身 Oracle 值, 期望值)
```

| 工具回读 | Oracle | 期望 | 结论 |
|---|---|---|---|
| == 期望 | == 期望 | — | **PASS**（双证据） |
| == 期望 | != 期望 | — | **FAIL**（工具读到自己缓冲，没真写入） |
| != 期望 | == 期望 | — | **FAIL**（工具回读路径有问题，但值其实写进去了） |
| != 期望 | != 期望 | — | **FAIL**（整个写入没生效） |
| — | — | — | 需先判断位点在不在（见下节） |

**注意第二行**：这是最隐蔽的 bug —— 工具报告一切正常，
但目标进程纹丝不动。**没有 Oracle 你永远发现不了。**

---

## 四、判据三分类的落地

### 探针先回答"位点在不在"

关键设计：把"能不能验证"与"验证结果"分成两步。
代码钩子类尤其需要 —— 因为替身默认**没有布钩子桩**。

```csharp
public enum ProbeVerdict
{
    Hit,            // AOB 命中，位点存在 → 可以继续 arm/disarm
    SiteAbsent,     // AOB 未命中 —— 目标进程不含该代码位点
    NotAHook,       // 该 flag 不是代码钩子类（无 AOB 定义）
    NotImplemented, // 钩子尚未实现
}

public readonly record struct ProbeResult(ProbeVerdict Verdict, string Text);
```

### 验收侧按 verdict 分流

```csharp
var probe = CodeHooks.Probe(flag, engine.TestMemory, engine.TestModule);

if (probe.Verdict is ProbeVerdict.SiteAbsent
                    or ProbeVerdict.NotImplemented)
{
    Skip(flag, $"{probe.Text}（目标进程无此代码位点，未接线验证）");
    return;
}

/* 位点存在 → 走真实的 arm/disarm */
engine.SetEnabled(flag, true, 2.0);
bool on  = engine.LastOk;  string onMsg  = engine.Message;
engine.SetEnabled(flag, false, 0);
bool off = engine.LastOk;  string offMsg = engine.Message;

Check(on && off, flag, "codehook",
      $"{probe.Text} | on:{onMsg} | off:{offMsg}");
```

**效果**：14 条在替身上必然缺失的钩子项，从 `FAIL=14` 变为 `SKIP=14`，
报告立刻变得可决策：

```
修复前：PASS=26 FAIL=14 SKIP=1   ← FAIL 数随替身能力波动，无决策价值
修复后：PASS=26 FAIL=0  SKIP=15  ← FAIL 全清，SKIP 有分类原因
```

---

## 五、SKIP 的原因必须分类

一个 SKIP 的原因若只写"跳过"，读报告的人无法判断
"这是环境限制还是我没干活"。必须带分类：

| 分类 | 原因文本示例 | 含义 |
|---|---|---|
| 无位点 | `AOB 未命中 [48 8B 05 ...]（目标进程无此代码位点）` | 环境不提供 |
| 未实现 | `god_mode: 未实现` | 我还没做 |
| 非地址类 | `xyz: 非 hook 类（无 AOB 定义）` | 分类错误 |
| 无数据源 | `该 flag 依赖 TGA 表运行期数据，需自研代码钩子` | 结构性缺失 |

验收脚本汇总时要**按分类分别统计**：

```python
skip_a = [r for r in rows if r[0] == "SKIP" and "代码位点" not in r[3]]
skip_b = [r for r in rows if r[0] == "SKIP" and "代码位点" in r[3]]

if skip_a:
    print(f" SKIP {len(skip_a)} 项为无运行期数据源者（需自研代码钩子）")
if skip_b:
    print(f" SKIP {len(skip_b)} 项为代码钩子类：替身未布该位点，"
          f"位点存在性与 arm/disarm 还原需在真机验证")
```

这样读报告的人一眼知道：**哪些项必须在真机上补验**。

---

## 六、报告模板

脚本终局必须打印**结论行** —— 人工只看这一行：

```
================================================================
 验收报告
================================================================
 PASS = 26    FAIL = 0    SKIP = 15
 交叉核对 (Oracle) : 3/3 一致
 构建: Debug OK / Release OK（0 警告 0 错误）
 产物新鲜度: 通过（产物 mtime > 源码 mtime）
----------------------------------------------------------------
 SKIP 15 项为代码钩子类：替身未布该位点（无钩子桩），
        位点存在性与 arm/disarm 还原需在真机验证
----------------------------------------------------------------
 结论: PASS
================================================================
```

### 每条明细都要带错误文本

```
[PASS] hp_freeze        data    read=100 write=9999 readback=9999 oracle=9999
[FAIL] stamina_refill   data    写入后回读=100 != 期望=9999 | oracle=100（未生效）
[SKIP] god_mode         codehook AOB 未命中 [48 8B 05 ? ? ? ?]（目标进程无此代码位点）
```

反面例子（信息量为零）：
```
[FAIL] stamina_refill   失败
```

---

## 七、Oracle 侧的常见坑

| 坑 | 症状 | 修法 |
|---|---|---|
| 忘记 `fflush` | Oracle 采样丢失 | 每行打印后 `fflush(stdout)` |
| 采样太慢 | 漏掉瞬态写入 | 200~500ms，且加 change 日志 |
| 读的是替身自己的缓冲 | Oracle 也成孤证 | Oracle 必须读**桩的原始变量** |
| change 日志无时间戳 | 无法与工具动作对齐 | 每行都带 `t=x.xxs` |
| 只采一个字段 | 位域互扰漏检 | 采全部相关字段，含互斥字段 |
| Oracle 输出混在 Mock 输出里 | 解析错乱 | 严格前缀分流 `[MOCK]` / `[ORACLE]` |

---

## 八、什么时候 Oracle = "恒真"，要警惕

如果 Oracle 的采样点**紧跟着**工具写入（同一进程内），
那它就不是独立证据 —— 它和工具读的是同一块内存的同一时刻快照。

**独立性的真正来源**：

1. **不同进程** —— 替身独立 exe（已由 `mock-process.md` 保证）
2. **不同代码路径** —— 替身读变量，工具走 `ReadProcessMemory`
3. **不同时间点** —— 周期采样 / change 事件

三者缺一，Oracle 的证明力就打折。特别是：
**如果替身和工具跑在同一进程里（如 in-process 测试），Oracle 就是假 Oracle。**
