# 把规范施工到既有工程（顺序 + 踩坑）

> 规范本体见 SKILL.md；本文件是**施工顺序**与**翻车点**。
> 实战：三个 STM32H7 工程（2026-09-30 一天内三次）全部双构零警告。

## 0. 施工范围判定（先做）

- 只动自研码：`app/`、`bsp/`、`Core/Src`、`Core/Inc`。
  CubeMX 的 `USER CODE BEGIN/END` 标记**必须保留**，改完数一遍数量。
- 豁免：`Drivers/`、`third_party/`、`stm32h7xx_hal_conf.h`（ST 文件）、`sys_startup/`、
  `*startup*.s`。
- **生成文件豁免**：脚本生成的表（带 `GENERATED` 头）、字体位图数据表（千行长行）——
  clang-format 的对齐规则会把数据表炸成 10 倍行数。
  数据表**只做去 tab**：`sed -i 's/\t/    /g'`，用 `git diff -w` 验证纯空白。

## 1. clang-format

- 配置从已施工工程根目录的 `.clang-format` 拷（clang-format 23.x 布尔值写法）。
- 用受管 venv 里的 clang-format：`python -m pip install clang-format`，
  然后 `<venv>/Scripts/clang-format.exe -i <files>`（**别写死绝对路径**，用 `command -v` 查）。
- **GBK 编码文件先验单文件**：比对非 ASCII 字节序列（>127）前后一致再批量。
  实测 clang-format 23.1.1 完整保留 GBK 字节（1004 B 逐字节 SAME）。
- 批量后查 `git diff --numstat`：单文件 `+N/-N` 应大致 1:1；出现暴增 = 炸了数据表，
  回退该文件（`git restore -- <path>`）。大小写改名重建暂存用
  `git rm -r --cached Bsp && git add bsp`。

## 2. 目录大小写改名（如 `Bsp` → `bsp`）

`git mv Bsp bsp_tmp && git mv bsp_tmp bsp`（**两步**，防 case-insensitive 文件系统拒绝）。

同步引用：`CMakeLists` / `uvprojx` / 脚本 / `.bat`（反斜杠形式 `\Bsp\`）/ docs。

提交拆分：**先提纯 rename（引用修正一起），再提 style** —— 否则逐行格式化会打断
rename 相似度检测，git 记成 D+A，断掉文件历史。

## 3. `extern "C"` 审计

```bash
for f in app/*.h bsp/*.h; do grep -L __cplusplus "$f"; done
```

缺失的头：在 include 防护 `#define` 之后插 `#ifdef __cplusplus extern "C" { #endif`，
文件末 `#endif` 前插闭合。⚠️ 有些文件是 GBK —— 按字节读写保留原编码。

## 4. static 合并（规范 §3，最易翻车）

- 逐文件 `grep -nE "^static [A-Za-z_].*;"` 盘点；**按家族拆**：
  统计计数器与引擎状态是两件事，不要因为"都在同一文件"就塞一个结构体。
- 命名：类型小写 `_t` 结尾（跟随工程既有惯例），实例 `g_` 前缀；成员去掉 `s_` 冗余。
- **非零默认值逐项搬**（血泪案：`s_next_id = 1u`、DCMI 采样极性）→ 用指定初始化器
  `static xxx_t g_x = {.next_id = 1u};`，并在成员注释里标「非零默认，不可清零」。
- `volatile` 落在**成员**上；ISR 引用的成员合并后逐个核对。
- 大文件用 Python 正则批量替换（`\bs_xxx\b` 词边界，**先长名后短名**：
  `s_free_n` 必须先于 `s_free`），完成后 `grep` leftover 必须为空。
- 全部文件内 static → 编译器兜底（漏改会直接编译不过，不会静默）。

## 5. MDK 同步

- 源集铁律照旧：`syscalls.c` 不入组、`mdk_target.c` 必留、HAL 按需。
- 组名小写：`<GroupName>` 在 **uvprojx 与 uvoptx 两侧同步改**（只改一侧会出问题）。

## 6. 构建验证

- GCC：**先确认工程用没用 CMakePresets**。用 presets 就 `cmake --preset release` /
  `cmake --build --preset release`（+ debug）；裸 `cmake -S . -B build` 不加载工具链，
  会误用宿主 `cc.exe`（报 `-mthumb` 不识别）——这是工程配置问题，不是代码问题。
- MDK：`"<Keil>/UV4/UV4.exe" -b -j0 <完整路径>\xxx.uvprojx -t <target> -o build_log.htm`
  ⚠️ **uvprojx 路径参数绝不能漏**，漏了 UV4 静默挂起（无 log、无 .o、无报错）。
  挂起判据：进程在，但 `build_log.htm` 不生成 + `Objects` 时间戳不动 → 杀进程重跑。
- 判据：末行 `0 Error(s), 0 Warning(s)`；半主机检查
  `fromelf --text -c Objects/*.axf | grep -c " BKPT"` 必须为 0。

## 7. 提交

- 本地 commit 不 push；rename 与 style 分开提；commit body 写清验证数据
  （双构零警告 + FLASH/RAM 字节数 + BKPT=0）。
