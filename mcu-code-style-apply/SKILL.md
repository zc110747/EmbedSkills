---
name: mcu-code-style-apply
description: 把 mcu-code-style 规范批量落到既有 STM32 工程：clang-format、GBK 编码保护、生成文件豁免、目录大小写改名、static 合并、MDK/GCC 双构验证与提交拆分。触发：给工程应用 code style、按新规范更新老项目。
agent_created: true
---

# mcu-code-style 应用流程（对既有工程施工）

> 规范本体见 `mcu-code-style`；本 skill 是**施工顺序 + 踩坑清单**。
> 实战：002（2026-09-30 上午）→ 003 → 004（同日下午），三次全部双构零警告。

## 0. 施工范围判定（先做）

- 只动自研码：`app/`、`bsp/`、`Core/Src`、`Core/Inc`（CubeMX USER CODE 标记**必须保留**，改完数一遍数量）。
- 豁免：`Drivers/`、`third_party/`、`stm32h7xx_hal_conf.h`（ST 文件）、
  `sys_startup/`（ST 派生模板）、`*startup*.s`。
- **生成文件豁免**：脚本生成的表（如 `lv_gbk_map.c` 有 "GENERATED" 头）、字体位图数据表
  （`drv_oled_fonts.c` 千行长行）——clang-format 的对齐规则会把数据表炸成 10 倍行数。
  数据表**只做去 tab**（`sed -i 's/\t/    /g'`），用 `git diff -w` 验证纯空白。

## 1. clang-format

- 配置从已施工工程拷（002/003/004 根目录 `.clang-format`，clang-format 23.x 布尔值写法）。
- pip 装 `clang-format`（受管 venv）：
  `C:/Users/lx176/.workbuddy/binaries/python/envs/default/Scripts/clang-format.exe -i <files>`
- **GBK 编码文件先验证**：对单文件跑一次，比对非 ASCII 字节序列（>127）前后一致再批量。
  实测 clang-format 23.1.1 完整保留 GBK 字节（1004B 逐字节 SAME）。
- 批量后查 `git diff --numstat`：单文件 +N/-N 应大致 1:1；出现暴增 = 炸了数据表，回退该文件
  （改名暂存态下用 `git restore -- <index路径>`；大小写改名重建暂存用
  `git rm -r --cached Bsp && git add bsp`）。

## 2. 目录大小写改名（如 Bsp→bsp）

`git mv Bsp bsp_tmp && git mv bsp_tmp bsp`（两步，防 case-insensitive fs 拒绝）。
同步引用：CMakeLists / uvprojx 路径 / 脚本 / .bat（`\Bsp\`）/ docs。提交拆分：
**先提纯 rename（引用修正一起），再提 style**，否则逐行格式化会打断 rename 相似度检测（D+A 断历史）。

## 3. extern "C" 审计

`for f in app/*.h bsp/*.h; do grep -L __cplusplus $f; done` → 缺失的头插守卫：
include 防护 `#define` 后插 `#ifdef __cplusplus extern "C" { #endif`，
文件末 `#endif` 前插闭合。注意有些文件是 GBK——按字节读写保留原编码。

## 4. static 合并（规范 §3，最易翻车）

- 逐文件 `grep -nE "^static [A-Za-z_].*;"` 盘点；**按家族拆**：统计计数器与引擎状态是两件事。
- 命名：类型小写 `_t` 结尾（跟随工程既有惯例），实例 `g_` 前缀；成员去掉 `s_` 冗余。
- **非零默认值逐项搬**（血泪案：`s_next_id = 1u`、DCMI 采样极性）→ 用指定初始化器
  `static xxx_t g_x = {.next_id = 1u};` 并在成员注释里标"非零默认，不可清零"。
- `volatile` 落在成员上；ISR 引用的成员合并后逐个核对。
- 大文件用 python 正则批量替换（`\bs_xxx\b` 词边界，**先长名后短名**：`s_free_n` 先于 `s_free`），
  完了 grep leftover 必须为空。全部文件内 static → 编译器兜底。

## 5. MDK 同步

- 源集铁律照旧：syscalls.c 不入组、mdk_target.c 必留、HAL 按需。
- 组名小写：`<GroupName>` 在 **uvprojx 与 uvoptx 两侧同步改**（只改一侧可能出问题）。

## 6. 构建验证

- GCC：**确认工程用没用 CMakePresets**。用 presets 就 `cmake --preset release` /
  `cmake --build --preset release`（+ debug）；裸 `cmake -S . -B build` 不加载工具链，
  会误用宿主 cc.exe（报 `-mthumb` 不识别）——这是工程配置问题，不是代码问题。
- MDK：`"C:/Keil_v5/UV4/UV4.exe" -b -j0 <完整路径>\xxx.uvprojx -t <target> -o build_log.htm`
  ⚠️ **uvprojx 路径参数绝不能漏**，漏了 UV4 静默挂起（无 log、无 .o、无报错）。
  挂起判据：进程在但 build_log.htm 不生成 + Objects 时间戳不动 → `taskkill //PID <pid> //F` 重跑。
- 判据：末行 `0 Error(s), 0 Warning(s)`；半主机 `fromelf --text -c Objects/*.axf | grep -c " BKPT"` = 0。

## 7. 提交

- 本地 commit 不 push；rename 与 style 分开提；commit body 里写清验证数据
  （双构零警告 + FLASH/RAM 字节数 + BKPT=0）。
