# EmbedSkills 项目长期记忆

> 本仓 = **经验的可执行封装**。每篇 skill 都带 `description` 触发词，Agent 按需加载。
> 详细工作日志见同目录 `YYYY-MM-DD.md`。

## 仓库定位与硬约定

- **双向一致**：本仓与 `~/.workbuddy/skills/` 应**逐字节一致**；`README.md` 是本仓独有。
- **改一处要回写两边**：在本仓改完 skill 后，必须把改动同步回系统目录，
  否则下次同步会把改动**回退**掉。
- **零删除**：整理时旧版本整体退役到带日期备份目录，不做原地删除。
- **单 commit**：一次同步/优化合成一个 commit；**commit 只在本地，push 由用户自己处理**。
- 不写 token / 凭据 / 密钥 / 内网地址。

## frontmatter 约定（每篇 SKILL.md 必须满足）

```
---
name: <与目录名完全一致>
description: ≤150 字符、含触发词、第三人称
agent_created: true
---
```

- **description ≤150 字符是硬约束**，写前先数。压缩时优先砍中文触发词、
  保留英文触发词（英文词触发权重更高）。
- 可用 `globs:` 指定适用文件类型（如 `["*.c","*.h"]`）。

## 三层加载模型

| 层 | 内容 | 何时加载 |
|---|---|---|
| L1 常驻 | `name` + `description` | 每会话自动注入（19 × ≤150 字符 ≈ 3 KB） |
| L2 按需 | `SKILL.md` 正文（目标 2~4 KB） | 触发词命中 |
| L3 精确 | `references/*.md` | 正文指向时才读 |

## 准入门槛（写新 skill 前自检）

1. **可判据** —— 能写成"满足 X 则 Y"，不是故事。
2. **可复现** —— 换项目/换板子仍成立，或明确标注适用芯片。
3. **有出处** —— 引脚、寄存器、时钟、型号都核对过，未核对显式标注。
4. **只写反直觉的部分** —— 常识不必写。

## 当前规模（2026-09-29）

19 skills / 78 references / 1124 行 SKILL.md / 9369 行参考资料。

## 工具环境陷阱（本机实测）

- `find` 被 Windows `FIND.exe` 遮蔽 → 用 Glob 工具或 Python `os.walk`。
- `cmd //c "..."` 从 Git Bash 调用被宿主安全策略拦 → 直接按路径执行 `.bat`。
- PowerShell 工具**吞 stdout**（返回 exit 0 但无输出）→ 统计/对比走 Bash + Python。
- **目录比对/统计的可靠配方**：Python `os.walk` + MD5 集合运算，
  输出 `A-B`（系统独有）/ `B-A`（本仓独有）/ 共有多方不一致 三张单子。

## 维护待办（README「规划」段）

- [ ] 同步脚本入仓（当前 `support_tools/sync_skills.sh` 在工程侧、白名单写死，
      增删 skill 后必须同步改脚本 → 计划改为目录自动发现）
- [ ] 安装脚本 `install.sh` / `install.bat`（Windows 侧纯 ASCII、pause-on-error）
- [ ] CI 一致性校验（frontmatter 完整性、description 字符数、references 链接有效性）
- [ ] `LICENSE` 文件仍缺失（README 已写 MIT 声明，内容见 `git show e6d337f^:LICENSE`）
