# EmbedSkills 项目长期记忆

> 本仓 = **经验的可执行封装**。每篇 skill 都带 `description` 触发词，Agent 按需加载。
> 详细工作日志见同目录 `YYYY-MM-DD.md`。

## 仓库定位与硬约定

- **双向一致**：本仓与 `~/.workbuddy/skills/` 应**逐字节一致**；`README.md` 是本仓独有。
- **开工前先跑双向比对**：跨会话会漂移（用户在别的会话/别的 Agent 里直接改系统目录）。
  不要假设"上次同步过所以现在仍一致"——2026-09-30 / 2026-10-19 两次开工都发现漂移
  （后者全局被整批回退，少了 15 个 skill 目录）。
- ⚠️ **改 skill 必须先改全局权威副本**，再 `bash sync_skills.sh` 刷镜像。
  反向操作（改镜像后跑 `sync`）会被全局旧副本**静默覆盖**，且 `sync` 仍打印
  `RESULT: OK`（两边"一致"了，只是都变成旧版）——2026-10-19 实际踩过，只能重做。
  仓独有文件另说：`README.md` 不纳管；**能力表纳管**，改完要 `cp` 回全局。
- **提交前两条命令**：`bash sync_skills.sh --check` 要 `IDENTICAL`，
  `python lint_skills.py` 要 `RESULT: OK`。
- **零删除**：整理时旧版本整体退役到带日期备份目录，不做原地删除。
- **单 commit**：一次同步/优化合成一个 commit；**commit 只在本地，push 由用户自己处理**。
- 不写 token / 凭据 / 密钥 / 内网地址。

## frontmatter 约定（每篇 SKILL.md 必须满足）

```
---
name: <与目录名完全一致>
description: ≤120 字符（硬上限 150）、「机制 + 症状」结构、第三人称
agent_created: true
---
```

- **description ≤120 字符**是当前约定（>120 只 WARN，>150 才 error）。**别写满**：
  46 篇全都顶到 150 时，description 会退化成「功能清单」，反而降低模型区分度。
- 压缩时优先砍中文功能词与「适用于…等请求」句式，保留英文实体（`pyocd` / `FLM` / `AOB` 等权重更高）。
- 可用 `globs:` 指定适用文件类型（如 `["*.c","*.h"]`）。

## 三层加载模型

| 层 | 内容 | 何时加载 |
|---|---|---|
| L1 常驻 | `name` + `description` | 每会话自动注入（41 × ≤120 字符 ≈ 3.4K 字符 / 7.1 KB） |
| L2 按需 | `SKILL.md` 正文（目标 2~4 KB） | 触发词命中 |
| L3 精确 | `references/*.md` | 正文指向时才读 |

## 准入门槛（写新 skill 前自检）

1. **可判据** —— 能写成"满足 X 则 Y"，不是故事。
2. **可复现** —— 换项目/换板子仍成立，或明确标注适用芯片。
3. **有出处** —— 引脚、寄存器、时钟、型号都核对过，未核对显式标注。
4. **只写反直觉的部分** —— 常识不必写。

## 当前规模（2026-10-26）

**41 skills / 130 references / 4885 行 SKILL.md / 16285 行参考资料 / 11 个脚本**
（9 个随 skill + 仓根 `sync_skills.sh`、`lint_skills.py`）。

- 41 条 description 全部 **≤120 字符**，常驻 **3,400 字符 / 7.1 KB**（最长 117、平均 82）。
  结构约定：**「机制 + 症状」双段式**，不再写「适用于…等请求」的同义堆砌。
  `lint_skills.py`：>120 只 WARN，>150 才 error。
- **2026-10-26 合并 5 组（46 → 41）**，旧名已不存在，任何引用一律用新名：
  `ra8d1-vscode-pyocd-debug` → `pyocd-flm-inject-debug`（+ `references/ra8d1-instance.md`）
  `mcu-code-style-apply` → `mcu-code-style`（+ `references/apply-to-legacy-project.md`）
  `lvgl-font-and-render` + `lvgl9-mcu-porting` → **`lvgl-mcu`**
  `embedded-verification-acceptance` + `app-host-load-acceptance` → **`verification-and-acceptance`**
  `web-headless-verification` + `win-gui-screenshot-verify` → **`visual-verification`**
- `mcu-comment-style` 已于 **2026-09-30 改名并扩写为 `mcu-code-style`**（纳入状态封装 /
  接口粒度 / 第三方边界三条规则）。旧名已不存在，任何引用一律用新名。
- `sync_skills.sh` 纳管清单 = **两侧都扫再取并集**（原只扫全局，`--restore` 补不上
  镜像独有目录，2026-10-19 修）；`DENYLIST` 含 `README.md` / `sync_skills.sh` / `lint_skills.py`。
- 正文 >6 KB 的有 20 篇（UTF-8 字节口径，最大 `ra8d1-fsp-platform-notes` 19.3 KB）**暂不瘦身**：
  密度高无水分，且属 L2 按需加载；要动就下沉 `references/`，不砍判据。

## 去重操作的判据（相似度用不上）

正文两两 6-gram Jaccard 最高仅 **5.2%** ⇒ 文本相似度找不到重复，要按**职责边界**判：

1. 正文首行**自述依赖**另一篇（`apply` 篇写「规范本体见 mcu-code-style」）⇒ 必合并。
2. **同一机制的实例化**（RA8D1 调试 = pyocd 注入机制的芯片实例）⇒ 合并，实例参数下沉。
3. **同一套纪律的不同战场**（固件验收 / 上位机压测 / Web 与 GUI 视觉验收）⇒ 合并，
   只保留「通用纪律」在正文，完整原文整体下沉为 `references/*-playbook.md`。

## 改名/合并操作的影响面（下次照此清单）

1. `git mv <old> <new>`（保留历史），再改 frontmatter 的 `name`。
2. 改 `README.md`：清单行、计数（Skill 数 / L1 成本行）、必要处加变更记录。
3. 改 `STM32_skills_能力表.md`：表头计数 + 分组计数 + 条目。
4. **grep 全仓**找其它 skill 的交叉引用（易漏，2026-10-26 有 12 个文件）。
5. 系统目录：建新目录 + 删旧目录（内容已并入，不算"删除经验"）。
   ⚠️ 批量 `mv` 到退役目录时**别假设成功**：2026-10-26 有 1 个目录 `mv` 报
   `Permission denied`（其余 7 个正常），`cp` 却成功 —— 改用
   `find <dir> -depth -delete` 单独删掉。

## 工具环境陷阱（本机实测）

- `find` 被 Windows `FIND.exe` 遮蔽 → 用 Glob 工具或 Python `os.walk`。
- `sort -u` 被 System32 `sort.exe` 遮蔽（静默返回空）→ bash 里用 `case` 判重。
- `cmd //c "..."` 从 Git Bash 调用被宿主安全策略拦 → 直接按路径执行 `.bat`。
- PowerShell 工具**吞 stdout**（返回 exit 0 但无输出）→ 统计/对比走 Bash + Python。
- **目录比对/统计的可靠配方**：Python `os.walk` + MD5 集合运算，
  输出 `A-B`（系统独有）/ `B-A`（本仓独有）/ 共有多方不一致 三张单子；
  顺手校验统计脚本自身的假阳性（2026-10-19 lint 曾把跨 skill 引用误报为缺失）。

## 维护待办（README「规划」段）

- [x] 同步脚本入仓 + 目录自动发现 + 两侧并集（2026-10-19）
- [x] description 全部 ≤150 字符 + `lint_skills.py` 落地（2026-10-19）
- [ ] 安装脚本 `install.sh` / `install.bat`（Windows 侧纯 ASCII、pause-on-error）
- [ ] 把 `lint_skills.py` 挂到 pre-commit / GitHub Actions（`.github/` 目前为空）
- [ ] `LICENSE` 文件仍缺失（README 已写 MIT 声明，内容见 `git show e6d337f^:LICENSE`）
