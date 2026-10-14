# 替身进程构造（mock-process）

目标：造一个**独立 exe**，它在内存里长成"真目标的样子"，让被测工具的所有地址类接线都能跑通。

---

## 一、为什么必须是独立进程

| 方案 | 验证了什么 | 结论 |
|---|---|---|
| 宿主进程内 `malloc` 假地址 | 只验证了指针算术 | ❌ 跨进程读写、权限、句柄全没走到 |
| 映射一个假模块 | 部分验证 | ⚠️ 不够，模块枚举/基址对齐仍可能错 |
| **独立 exe + 真实模块基址** | 打开进程→枚举模块→算偏移→读写→回读 | ✅ 唯一可信 |

关键：被测工具是通过 `OpenProcess` + `ReadProcessMemory` 访问的，
那么**被测对象就必须是另一个进程**。没有例外。

---

## 二、目录与构建隔离

```
tools/mock/                     独立目录，不混进主工程
├── mock_main.c                 替身源码
├── build.bat / build.sh        单独构建
└── out/eldenring_mock.exe      产物
```

**为什么必须隔离**：主工程的 `obj/` 里混入替身产物，
后续"产物新鲜度闸门"会互相干扰；清理时也容易误删。
替身产物**单独目录**，验收脚本里显式引用其完整路径。

---

## 三、桩的三种类型

### 类型 1：数据桩（数据基址）

直接可读写的结构体。用于「直接基址类」功能（读/写某个固定地址的值）。

```c
/* 桩区集中定义，便于核对布局 */
#pragma pack(push, 4)
typedef struct {
    volatile int32_t hp;          /* +0x00  int32 */
    volatile float   stamina;     /* +0x04  float  */
    volatile uint8_t flags;       /* +0x08  位域容器 */
    volatile int32_t souls;       /* +0x0C  int32 */
} DataStub;
#pragma pack(pop)

static DataStub g_data;   /* 桩实例 —— 地址 = &g_data */
```

**要点**：
- `#pragma pack(4)` 或显式对齐 —— 避免编译器插 padding 导致偏移对不上
- 全部 `volatile` —— 见下文"守门校验"一节
- 字段顺序/类型/偏移**照抄逆向结论**，不能随手改

### 类型 2：指针链桩

三级链就埋三块内存：

```c
static volatile uintptr_t g_chain_L1;  /* 存 &g_node_L2 */
static volatile uintptr_t g_chain_L2;  /* 存 &g_node_L3 */
static volatile int32_t   g_chain_L3;  /* 最终值 */

/* 第三趟回填 */
g_chain_L1 = (uintptr_t)&g_chain_L2;
g_chain_L2 = (uintptr_t)&g_chain_L3;
g_chain_L3 = 100;                       /* 初始值 */
```

工具的遍历序必须是：`obj = ReadInt64(符号地址)` → 逐项 `obj = ReadInt64(obj + off)`
→ **末偏移只加不解引用** → 读写。

> 若逆向结论是"末级还要解引用一次"，就再埋一层。
> **替身的层次必须与逆向结论完全一致**，否则验证的是另一套算法。

### 类型 3：AOB 桩（代码/字节模式）

一段**固定字节串 + 通配位**，让扫描器命中：

```c
/* 用数组强制布局，并禁止优化消除 */
static volatile uint8_t g_aob_stub[] = {
    0x48, 0x8B, 0x05, 0x00, 0x00, 0x00, 0x00,   /* 锚点：固定 7 字节 */
    0x48, 0x85, 0xC0,                            /* 固定 */
    0x74, 0x00,                                  /* 通配 1 字节 */
    0x48, 0x89, 0x58, 0x08,                      /* 固定 */
};
```

对应 AOB 描述串：`48 8B 05 ? ? ? ? 48 85 C0 74 ? 48 89 58 08`

**要点**：
- 锚点段要**足够长**（≥6 字节固定）才不易假命中
- 通配位写在真正会变的字节上（如相对偏移、跳转目标）
- 数组必须是 `volatile` 且**被实际引用**，否则会被链接器丢掉

---

## 四、AOB 桩自检：命中必须等于自身

这是替身侧最重要的一条断言：

```c
/* 替身启动后自检：把扫描到的地址和自己登记的地址比对 */
uintptr_t self = (uintptr_t)g_aob_stub;
printf("[MOCK] aob_stub @ 0x%p  pattern=%s\n", (void*)self, AOB_PATTERN);
```

验收脚本侧：

```
scanned = scan(AOB_PATTERN)
assert scanned == mock_reported_addr   # 不等 → 桩埋错 or 通配符展开错
```

**这条断言把两类问题当场分开**：

| 现象 | 结论 |
|---|---|
| 命中 == 桩地址 | 桩有效，扫描器正确；后续失败是**接线**问题 |
| 命中 != 桩地址（多命中） | 锚点太短，出现假命中 → 加长锚点 / 加全量校验 |
| 零命中 | 桩被优化掉了 / 通配符展开错 / 读窗口越界 |

没有这条自检，零命中时你会在"改扫描器"上浪费几个小时。

---

## 五、三趟建图（顺序不可颠倒）

```
第一趟：登记所有桩地址
        → 把 &g_data / &g_chain_L1 / g_aob_stub 全部打印或写入共享区
        → 此时地址已确定，但指针链尚未连通

第二趟：按需布指针链
        → 按逆向后端要求的层次，决定埋几级、每级放什么类型

第三趟：回填指针
        → g_chain_L1 = &g_chain_L2; g_chain_L2 = &g_chain_L3;
        → g_chain_L3 = 初始值
```

**为什么不能颠倒**：如果先回填指针、后登记地址，
登记时读到的是未初始化的 `L2/L3` 地址；
如果先回填又先登记，中途被工具读到，工具会遍历到野指针并**静默失败**。

**实践**：把三趟写成三个函数，主函数顺序调用，
并在每趟之间 `Sleep(200)` 留出观测窗口（便于调试时抓快照）。

---

## 六、无引用根节点必须预先登记

有些指针链的"根"是**只有指针引用它、它自己不在任何全局符号里**的节点。
工具按符号名找不到它，会直接报"符号不存在"。

修法二选一：

**方案 A（推荐）**：替身把根地址**显式导出**
```c
/* 供验收脚本/调试读取的登记表 */
typedef struct { const char* name; uintptr_t addr; } StubEntry;
static volatile StubEntry g_registry[] = {
    { "player_ptr",  (uintptr_t)&g_chain_L1 },
    { "hp",          (uintptr_t)&g_data.hp   },
    ...
};
```

**方案 B**：在替身里加一个独立全局符号，工具的符号解析步
（`symAddr = hit + 7 + ReadInt32(hit + 3)`）能命中它。

> 无论哪种，工具侧要支持"按登记名取地址"这条路径，
> 否则就得为每个根节点写死偏移，替身一改布局就全崩。

---

## 七、volatile 与守门校验（防优化器吃掉桩）

**问题**：`-O2/-Os` 下，只被写、从不被读的变量会被整个消除。
表现是"工具报告写入成功，但值没变"。

**双保险**：

```c
/* 保险 1：变量本身 volatile */
static volatile int32_t g_data_hp;

/* 保险 2：替身自己周期校验并打印 —— 让变量被真正读取 */
static void guard_tick(void) {
    /* 这些读取强制变量存活 */
    int32_t hp = g_data_hp;
    if (hp > 100000 || hp < -100000)
        printf("[MOCK][WARN] hp 越界: %d\n", hp);
}
```

替身主循环里每 500ms 调一次 `guard_tick()`。
这样即使开启最高优化，桩也不会被删除。

**额外收益**：`guard_tick` 的越界告警本身就是一条**替身侧证据**
—— 工具写了个离谱的值，替身会立刻喊出来。

---

## 八、替身的输出契约

替身必须往 stdout 打印**结构化、可解析**的行，供验收脚本采集：

```
[MOCK] base=0x00007FF6A1230000
[MOCK] stub hp:      addr=0x.../hp=100
[MOCK] stub stamina: addr=0x.../stamina=100.0
[MOCK] aob_stub @0x...
[ORACLE] t=0.50s hp=100 stamina=100.0 souls=0
[ORACLE] t=1.00s hp=9999 stamina=100.0 souls=0    <- 工具写入了
```

- `[MOCK]` 前缀 = 启动期登记信息（只打印一次）
- `[ORACLE]` 前缀 = Oracle 采样（周期性，见 `oracle-and-verdicts.md`）
- 脚本用前缀分流解析，**不要依赖固定行号**

---

## 九、替身常见坑

| 坑 | 症状 | 修法 |
|---|---|---|
| 桩被优化掉 | 零命中 / 写入无效 | `volatile` + 守门读取 |
| 缺 `#pragma pack` | 字段偏移整体错位 | 显式 pack，或加 `static_assert` 校验 `offsetof` |
| AOB 锚点太短 | 多命中，扫到无关区域 | 加长固定段，或加全量固定字节校验 |
| 指针链顺序颠倒 | 工具遍历到 0 地址 | 三趟建图，顺序固定 |
| 替身退出太快 | 工具还没连上就没了 | 主循环 `while(1) Sleep(...)`，加退出信号 |
| 位域写入不留原字节 | 改 flag A 把 flag B 也改了 | 读-改-写：先读整字节，改目标位，再写回 |
| 32/64 位不匹配 | `OpenProcess` 失败 | 替身与工具**同为 x64** |
| 路径含非 ASCII | 构建脚本乱码 | 构建用纯英文路径 + 纯英文输出 |

---

## 十、最小替身骨架

```c
/* mock_main.c —— 骨架示意，实际布局照抄逆向结论 */
#include <windows.h>
#include <stdio.h>
#include <stdint.h>

#pragma pack(push, 4)
typedef struct { volatile int32_t hp; volatile float stamina; } DataStub;
#pragma pack(pop)

static DataStub g_data = { 100, 100.0f };
static volatile uintptr_t g_chain_L1, g_chain_L2;
static volatile int32_t   g_chain_L3;
static volatile uint8_t   g_aob_stub[] = { 0x48,0x8B,0x05,0,0,0,0, 0x48,0x85,0xC0, 0x74,0, 0x48,0x89,0x58,0x08 };

int main(void) {
    /* 第一趟：登记 */
    printf("[MOCK] base=0x%p\n", (void*)GetModuleHandle(NULL));
    printf("[MOCK] hp addr=0x%p\n", (void*)&g_data.hp);
    printf("[MOCK] aob_stub @0x%p\n", (void*)g_aob_stub);

    /* 第二/三趟：布链 + 回填 */
    g_chain_L1 = (uintptr_t)&g_chain_L2;
    g_chain_L2 = (uintptr_t)&g_chain_L3;
    g_chain_L3 = 100;

    printf("[MOCK] ready\n"); fflush(stdout);

    uint32_t t = 0;
    while (1) {
        /* 守门 + Oracle 采样 */
        if (t % 500 == 0)
            printf("[ORACLE] t=%.2fs hp=%d stamina=%.1f\n",
                   t / 1000.0, g_data.hp, g_data.stamina);
        fflush(stdout);
        Sleep(100);
        /* 桩存活保证：显式读取 */
        if (g_aob_stub[0] != 0x48) printf("[MOCK][WARN] aob 桩被改写\n");
        t += 100;
    }
}
```

构建（MSYS2 mingw64，x64）：

```bash
gcc -O2 -m64 -o out/eldenring_mock.exe mock_main.c
```

> `-O2` 用来**逼迫**你正确使用 `volatile`；能在 `-O2` 下跑通才算合格。
