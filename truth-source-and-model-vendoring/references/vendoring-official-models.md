# 官方模型（URDF / MJCF / STL）引入自有工程

适用：把上游仓库或厂商 SDK 的机器人模型接入自有代码库，并让自有配置（尺寸 / 限位 / 标定 /
物理量）与官方模型**长期一致**。上游可来自任意来源，下述判据与来源无关。

## 铁律 1 · 同一模型的两份官方描述**经常不一致**

上游常同时发布 URDF 与 MJCF（两者都由 CAD 导出，但导出器不同、精度不同）。
**不要假设它们等价 —— 逐位对一遍。** 两类必查差异：

| 差异类型 | 典型现象 | 裁决 |
|---|---|---|
| **朝向 / 帧定义** | 同一个 TCP 帧，URDF 用 `rpy=[0,π,0]`，MJCF 用 `quat=Ry(π/2)` ⇒ **差 90°**；平移逐位相同 | 取**运行期用的那份**。取对后姿态残差可到 `0.001°` 量级，取错就是 `90.0004°` |
| **数值精度** | URDF 把 rad **截断到 6 位有效数字**（`1.5708` ≠ π/2）；MJCF 满精度 | 取**引擎执行的那份** ⇒ 限位取 MJCF，才能保证"配置声明的区间 ≡ 仿真区间" |

**排查手法**：先做一次 FK 交叉验证（自实现 FK vs 引擎 FK），若误差是 **µm 级** → 是精度差；
若是 **mm / 十度级** → 是约定或帧定义用错。**先把残差量出来再改东西。**

## 铁律 2 · 物理量从**已加载的模型对象**读，不解析 XML 文本

MJCF 的 `<default class>` 会被**逐实例覆盖**，文本会骗人：

```xml
<default class="servo"><position kp="998.22" forcerange="-2.94 2.94"/></default>
<actuator>
  <position class="servo" name="shoulder_pan" ... forcerange="-3.35 3.35"/>  <!-- 覆盖 -->
</actuator>
```

⇒ 解析 XML 会读到 `±2.94`，而实际生效是 `±3.35`。
且官方常**没有 `<option>` 段**（timestep / integrator / solver 全是引擎缺省值）——
**这些值根本不在文本里**，只有引擎才知道。

```python
import mujoco
m = mujoco.MjModel.from_xml_path(path)
o = m.opt                                  # timestep / integrator / solver / iterations / gravity
m.dof_damping[...] / m.dof_frictionloss / m.dof_armature
m.actuator_gainprm[a][0]                   # position 执行器的 kp
-m.actuator_biasprm[a][2]                  # kv
m.actuator_forcerange[a] / m.actuator_gear[a][0]
m.body_mass[b] / m.body_ipos[b] / m.body_inertia[b]
m.geom_contype[g] / m.geom_conaffinity[g] / m.geom_group[g]
m.jnt_range[j]                             # 满精度限位
```

## 铁律 3 · 参数只有一份；配置**只负责选择**

```
config/robots.yaml                ← 只允许 id / name / config 三个字段（"有哪些、默认谁"）
config/robots/<id>/robot.yaml     ← 该机构的参数（唯一真值）
```

把参数"顺手"抄进选择器 = 制造第二份真值 ⇒ 禁止。
新增机构的正确姿势 = 丢一个配置文件 + 加一行选择器，**不改代码**。

## 防止"配置过期"的三件套

模型升级 / 有人手改官方文件时，自有配置会**静默变成过期的断言**。把它变成会失败的检查：

1. **审计快照**：把引擎读到的生效值写进配置的 `observed:` 段
   （**声明它不是真值，是"真值的指纹"**）。
2. **`--check` 脚本**：重新从引擎读一遍，逐键比较，有差异则 `exit 1` 并**逐字段列出**。
   - 浮点用 `abs_tol=1e-9`；跳过 `role` / `kind` 这类描述性字段。
   - 顺带做**唯一性断言**：若若干关节的参数本该一致却出现两个值 ⇒ 说明上游拆了 class，
     **当场失败**（配置的单值写法已不成立），而不是产出一个"看起来正常"的结果。
3. ★ **反向验证（最容易漏）**：**必须**验证校查器真能抓到漂移。
   做法：在内存里改 `kp / damping / timestep / mass`、删一段，确认全部被抓出。
   > 不做这一步，得到的是一个**永远为真**的断言 —— 它比没有检查更糟。

配套：生成器也要有 `--check`（`gen_*.py --check`），让"模型改了但派生配置没跟着改"同样失败。

## 派生配置的三条落地纪律

1. **只换单位，不改数值**：m→mm 用 `×1000`、rad→deg 用 `×180/π`，保留足够有效位、去尾零、消 `-0.0`。
   头部注释写明"派生自官方 X，未改数值"。
2. **欧拉角原样承载，不换算**：URDF `<origin rpy>` 是 **fixed-axis XYZ（`Rz·Ry·Rx`）**，
   ≠ 常见的 intrinsic XYZ（`Rx·Ry·Rz`）。让配置**声明约定**（如 `rotationConvention: rpy`）而不是换算 ——
   换算后配置里会出现一批**在官方文件里查不到的数**，从此无人能复核有没有抄错。
   渲染层映射：`'rpy'` → three.js Euler order `'ZYX'`，**数值三元组原样传入只换 order**。
3. **不要凭空造真值**：
   - `Link.length` 若 URDF 把完整位移写在 `joint.origin.position` 里，就**恒为 0**——
     硬拆一个 `Tz(length)` 出来只会多一个真值。
   - 执行器若官方是"关节空间位置伺服"（`ctrlrange ≡` 关节 range、`gear=1`），
     就**不要**编一段 scale 去把角度压进某个显示区间；给它一个**带缺省的新维度**
     （如 `unit: 'joint'`，缺省 `'deg'`），保证旧模型的逐值行为不变。

## 把"官方没声明的"显式写出来

在配置里留一节 `not_declared_by_official:`。官方模型常缺：

- **无 ground / table**（模型"悬空"，臂不会撞到任何东西）
- **无 `<contact><exclude>`** ⇒ 相邻连杆**默认会互相碰撞**（它们在关节处必然几何重叠）
- **无关节速度上限** ⇒ 位置执行器可瞬时趋近（只有 kp/kv 与 forcerange 限制）
- **无独立标定段**（标定已烘进关节原点与限位）
- **质量来自 CAD 导出，不是对某台实机称重**

> 把"缺失"写下来，否则缺失会被默认成"应该有、大概没问题"。

**绝不为了"让仿真更好看 / 更稳"而改官方文件**（改了就再也不是"官方模型"）。
需要偏离时，只在**运行期**用引擎 API 覆盖，并留一条 ADR 说明为什么。

## 目录布局：保留上游布局，换取"两份文件零修改"

若 MJCF 声明 `meshdir="assets"`、URDF 用 `assets/xxx.stl`，就在自有仓库里**复刻同名子目录**：

```
assets/models/<robot>/official/
├── <name>.urdf      <name>.xml          # 逐字节原样
├── LICENSE
├── assets/*.stl     ← ★ 子目录名不可改（改了就要动官方文件）
├── README.md        # 上游说明
└── SOURCE.md        # ★ 自己的：来源 repo / 固定 commit / 全部 sha256 /
                     #   勘误 / 裁决（哪份文件在哪一点上被采信，为什么）
```

验证"零修改可直接加载"：`MjModel.from_xml_path(...)` 打印 `nq / nv / nu / nmesh` 对一遍。

## 交叉验证的黄金值必须来自**对方**

自实现 FK 的判据不能用自己的 FK 算一遍（那是自证）。取**引擎给出的值**：

```python
d.qpos[:] = np.deg2rad([...]); mujoco.mj_forward(m, d)
d.site_xpos[frame_id] * 1000      # 位置（mm）
d.site_xmat[frame_id]             # ★ 姿态用**旋转矩阵**，不要反解成欧拉角
```

姿态比对必须用**旋转矩阵**（或四元数）：反解成欧拉角再比，会在万向锁附近产生
"其实完全等价却差了几十度"的**假失败**。容差按实测值给，并在注释里写清**根因**
与"离实测有多少倍余量、能拦住哪类错误"。

## STL 格式核验（一行辨真假）

不要相信"ASCII STL"的记载（上游 README 或自己的旧笔记都可能错）：

```python
import struct
n = struct.unpack('<I', data[80:84])[0]
assert len(data) == 84 + 50 * n     # 二进制 STL 的充要判定
```

`grep -c 'facet normal'` 返回 0 且报 "ignored null byte" ⇒ **是二进制**，不是 ASCII。
二进制 STL 是现代导出器的默认输出，three.js / MuJoCo 都直接吃，**无需任何转换**。

## 常见坑

| 坑 | 症状 | 处理 |
|---|---|---|
| 关节顺序 ≠ 期望 | 配置里 joint 声明顺序与引擎 `qpos` 顺序不一致 | 在 FK 交叉验证里同时断言顺序；打印 `name → qposadr` |
| 目标帧与活动夹具同挂一个 body | 取"第一个子关节"的逻辑拿错对象 | 目标帧必须声明在活动关节之前 |
| `links[].geometry` 写成列表 | 解析器按对象读 ⇒ 直接抛错 | schema 若为"单个主件 + `details` 列表"，生成器要区分缩进 |
| 循环导入 | `loader ↔ registry` 互相 import | 把错误类 / id 常量抽成**零依赖叶子模块**（别靠 ESM 的容忍度） |
| 死代码被 tree-shake | 新引擎在产物里搜不到字符串 | 若它确实还没被 app 调用，属**预期** |

## 模型**运行期切换**：从"能加载"到"能切"

接完第二台机构后，"能加载"只是第一步 —— 真正的判据是**能切且不残留**。

### 1 · 活动模型必须是 **state**，不是模块常量

```ts
// ✗ 换不掉：几十处消费点都读这个常量
const model = loadRobotModel('<pkg-id>');

// ✅ id + model 进 store；常量降级为"仅用于构造初始 state"并改名
const initialModel = loadRobotModel(defaultRobotId());   // 名字要能自证"只是初值"
```

配套两条：

- **纯函数显式收 `model`**（`clipJointState(model, …)`）—— 否则"用旧模型的限位裁新模型的关节"
  会**静默**产出越界角。
- **派生选择器用可选参数保兼容**：`jointLabel(jointId, model = activeModel())`。
  既有调用点与既有测试一行不改，多机构语境又能显式传入。

### 2 · 切换必须有**守卫**，且拒绝要说清"为什么 + 怎么修"

在**已接入传输**（正在驱动真机）时切换模型 = 把"能发什么"悄悄换掉 ⇒ **拒绝**并提示先断开。
同一条哲学也适用于其它状态切换：**校验全通过才改状态**，而不是改了状态再 pushLog 抱怨
（后者会留下"UI 显示 A、实际是 B"的状态）。

### 3 · ★ 同名关节会骗你："键集合相等"不是模型一致的判据

两台机构各有一个**同名**关节（比如都叫 `gripper`），而限位不同：

| | 机型 A | 机型 B |
|---|---|---|
| 同名关节限位 | `0 .. 90` | `-10 .. 100` |

⇒ 用"切换后关节键集合 == 新模型的键集合"当判据时，**这一个关节永远不会被发现**。
**只有限位（以及语义）能兜住它。** 切换判据必须同时有：

1. 键集合相等（抓"整台换错"）
2. **每个值落在新模型自己的限位上**（抓"同名不同义"）
3. 旧模型**独有**的键在新状态里**整个不存在**（`not.toHaveProperty`，抓"残留"）

### 4 · 切换压力回归：往返 N 轮后与初始**逐位相同**

只测一次切换会漏掉"某轮之后开始残留"的漂移：

```ts
const initial = snapshot();                 // 只取与模型绑定的字段
for (let i = 0; i < 200; i++) { switchTo(B); assertInvariants(B); switchTo(A); assertInvariants(A); }
expect(snapshot()).toEqual(initial);        // ★ 逐位相同
```

同时把"同 id 切换是**幂等**的"也钉住 —— 压力测试自己会调它上万次，
若每次重算 / 重写状态，压测本身就成了噪声源。

### 5 · ★ 注册表 id ≠ 模型 id

选择器 key 与模型自己声明的 id 常不同名，切换时才会暴露。
⇒ **禁止用模型自声明的 `model.id` 反查选择器**。要按**配置文件路径反查**：

```python
def resolve_entry_by_config(config_path):   # 两条路都要有，各端各一份
    ...
```

反过来，"配置里加了一台但代码里没有对应引擎"是必然出现的中间状态 ⇒ 用一张
**`assertRegistryCoverage()` 自检表**把它变成明确错误，别让业务代码长出 `if robot == …`。
