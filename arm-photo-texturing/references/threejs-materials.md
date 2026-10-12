> 本文件是 `arm-photo-texturing` 的明细参考，由 SKILL.md 拆出。
> 主题：three.js 材质数组与贴图朝向

# 5. three.js 侧：`RoundedBoxGeometry` 必须按面用材质数组

**实测**：`RoundedBoxGeometry`（three/addons 的圆角盒）继承 `BoxGeometry`，并且
**每个面的 UV 各自铺满 [0,1]、与长宽比无关**（圆角段还占了一段 UV）。

⇒ **直接 `mesh.material = new MeshStandardMaterial({ map: photo })` 是错的**：
6 个面会各显示一遍同一张图，而且被**非等比拉伸**（面的长宽比 ≠ 图片长宽比）。

**正确做法**：材质数组 + 只给目标面挂 `map`。

```js
// 实测（three 0.186）：groups 有 6 个且覆盖全部顶点 ⇒ 材质数组可用
// materialIndex → 面（与 BoxGeometry 官方顺序一致）：
//   0=+X  1=-X  2=+Y  3=-Y  4=+Z  5=-Z
const mats = Array.from({ length: 6 }, () => new THREE.MeshStandardMaterial({ color: baseColor }));
mats[bigFaceIndex].map = photoTexture;        // 只给大面挂图
mesh.material = mats;
```

**大面的 `materialIndex`** = `size` 里最小那一维对应的轴：
`X最小→0/1`、`Y最小→2/3`、`Z最小→4/5`（成对，正负两面都挂）。

> 别靠推理，**写个 10 行探针打出来**：遍历 `geometry.groups`，对每个 group 求顶点
> 包围盒跨度，跨度最小的那一维就是该面的法向，再对照 `grp.materialIndex`。
>
> ⚠️ 探针里有个必踩的坑：**`RoundedBoxGeometry` 是「非索引几何」**（`g.index === null`），
> group 的 `start/count` 是**顶点范围**而不是索引范围 —— 按 `g.index.array` 去遍历会直接
> `TypeError`（实测）。

## ★★ 朝向：`TextureLoader` 默认 `flipY = true` —— 图像顶行 ⇔ `uv_v = 1`

**这一条极易漏，漏掉会让所有 v 方向的推理整体反号。**
three 在上传纹理时默认做一次垂直翻转 ⇒ `uv_v = 1` 对应**图像第一行（顶部）**，而不是 0。
它不会报错、类型检查也查不出，只会让你"推导得头头是道、贴上去是反的"。

再接上"两个大面的 Δu/Δv **必有一个相反**"（盒体展开的必然结果）⇒
**同一张照片必有一面需要镜像**，否则从两侧看总有一侧左右/上下反。

实测 UV 表（`RoundedBoxGeometry(22,5,74, 2, 2)`，可直接当判据基线）：

| group | 法向 | Δu | Δv |
|---|---|---|---|
| 0 | +X | `-Z` | `+Y` |
| 1 | −X | `+Z` | `+Y` |
| 2 | +Y | `+X` | `-Z` |
| 3 | −Y | `+X` | `+Z` |
| 4 | +Z | `+X` | `+Y` |
| 5 | −Z | `-X` | `+Y` |

翻转用 `texture.repeat.set(±1, ∓1)` + `offset`（取负时 offset 补 1），
**不要用 `texture.flipY`** —— 后者只在**上传时**生效（对 `ImageBitmap` 等路径无效），
`repeat` 是在着色器里做的，一律可靠。同时把 `wrapS/wrapT` 设成 `ClampToEdge`
（`Repeat` 会让翻转后采到对侧像素），并显式设 `colorSpace = SRGBColorSpace`
（不声明会让整块板偏暗）。

## ★★★ 怎么定案：**四象限探针纹理**（受控实验）

**不要靠目视或推断定朝向。** 真实纹理通常是近黑工程塑料，特征只有零星高光，
而模型的细节件位置（如端盖在中线）与实物（有偏移）本就不同 ⇒ 读数会在
0.1~0.6 之间飘，"像"与"不像"都能自圆其说。

做法：把目标纹理**临时替换**成「四象限纯色 + 对角白带」（红/绿/蓝/黄 + 一条
`(0,0)→(1,1)` 的白带），同机位各拍一张（正对每个大面），读颜色分布，然后**还原**：

```python
a[:H//2, :W//2] = (255,0,0)    # 上左
a[:H//2, W//2:] = (0,255,0)    # 上右
a[H//2:, W//2:] = (0,0,255)    # 下右
a[H//2:, :W//2] = (255,255,0)  # 下左
```

判据无歧义：屏幕上四象限颜色与探针图一致 ⇒ 该面「不翻」；上下互换 ⇒ v 反；左右互换 ⇒ u 反。
**两面都要拍** —— 正确的状态是「两侧各自正确、且互为镜像」（真实物体两面的关系）。

⚠️ 还原后**必须 `git status` 复核干净**（临时覆盖的是入库文件）。
⚠️ 采样时别手估裁剪框：板的屏幕宽度常达 180px，手估很容易切掉一半，
读数就成了假的（实测吃过一次）。要么按行找**最长连续高饱和段**自动定位，要么直接把
探针图放大到一眼可读。

## 工程侧的三个必要守卫

| 守卫 | 不加会怎样 |
|---|---|
| **无 DOM 时不加载纹理** | `TextureLoader` 内部走 `document.createElementNS`，而单测常跑在 **node 环境** ⇒ 直接 `ReferenceError: document is not defined`，把整棵对象树建不出来（纹理不参与任何几何判定，"无 DOM ⇒ 按没配纹理处理"是正确取舍） |
| **key 未登记 ⇒ warn + 回退纯色** | 贴图失败**不报错**（静默），"文件名打错一个字"会安静地表现为"板没变色" |
| **纹理长宽比 == 板大面长宽比** | 抓"把 A 件的图配到 B 件"——写进单测，容差 5% |

## 配置化：新增纹理不该需要改代码

纹理路径写在**模型配置**里（如 `robot.yaml` 的 `links[].geometry.texture: <相对 assets/textures 的 key>`），
配一个 `import.meta.glob('.../assets/textures/**/*.png', { eager: true, query: '?url', import: 'default' })`
的注册表把 key 映射成 URL —— Vite 必须**在构建期**看到 import 才能把资源打进产物，
而配置里的路径是运行时字符串（`import(path)` 这种动态形式 Vite 无法分析）。
好处：**新增纹理只丢文件进目录，零代码改动**。

> 别忘了外观层与运动学层的解耦前提：贴图只改材质/几何显示，`length` / 关节 / 标定一律不动
> —— 若项目有"真值冻结"机制，正好可以借它证明这一点。

---
