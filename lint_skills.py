#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_skills.py — Skill 仓结构一致性校验（零依赖，可直接进 CI）。

检查项：
  1. 每个 skill 目录都有 SKILL.md
  2. frontmatter 闭合，含 name / description / agent_created: true
  3. name 与目录名完全一致
  4. description >150 为错误（L1 常驻成本硬约束）；>120 只告警（2026-10-26 起的新约定，
     留余量避免再次全员顶格堆砌）
  5. 正文首行是 H1
  6. 正文引用的 references/*.md 真实存在（支持 `其他skill/references/x.md` 跨引用）

用法：
  python lint_skills.py          # 校验脚本所在目录
  python lint_skills.py <dir>    # 校验指定目录

退出码：0 = 全通过；1 = 有问题。
"""
import os
import re
import sys

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
DENY_DIR = {".git", ".workbuddy", "references", "scripts"}


def main() -> int:
    problems = []
    warns = []
    skills = []

    for name in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, name)
        if not os.path.isdir(d) or name in DENY_DIR or name.startswith("."):
            continue
        sp = os.path.join(d, "SKILL.md")
        if not os.path.isfile(sp):
            problems.append((name, "缺 SKILL.md"))
            continue
        skills.append(name)

        with open(sp, encoding="utf-8", errors="replace") as f:
            txt = f.read()

        if not txt.startswith("---"):
            problems.append((name, "无 frontmatter 起始 ---"))
            continue
        end = txt.find("\n---", 3)
        if end < 0:
            problems.append((name, "frontmatter 未闭合"))
            continue
        fm, body = txt[3:end], txt[end + 4:]

        m = re.search(r"^name:[ \t]*(.+)$", fm, re.M)
        if not m:
            problems.append((name, "frontmatter 缺 name"))
        elif m.group(1).strip() != name:
            problems.append((name, "name(%s) != 目录名" % m.group(1).strip()))

        m = re.search(r"^description:[ \t]*(.*)$", fm, re.M)
        if not m or not m.group(1).strip():
            problems.append((name, "frontmatter 缺 description"))
        elif len(m.group(1)) > 150:
            problems.append((name, "description %d>150" % len(m.group(1))))
        elif len(m.group(1)) > 120:
            warns.append((name, "description %d>120（软约束，建议压到 ≤120 留余量）" % len(m.group(1))))

        if not re.search(r"^agent_created:[ \t]*true[ \t]*$", fm, re.M):
            problems.append((name, "缺 agent_created: true"))

        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        if not first.startswith("# "):
            problems.append((name, "正文首行非 H1: %r" % first[:40]))

        for owner, ref in set(re.findall(
                r"(?:([A-Za-z0-9_.\-]+)/)?references/([A-Za-z0-9_.\-]+\.md)", txt)):
            base = os.path.join(ROOT, owner) if owner and os.path.isdir(os.path.join(ROOT, owner)) else d
            if not os.path.isfile(os.path.join(base, "references", ref)):
                label = "%s/references/%s" % (owner, ref) if owner else "references/%s" % ref
                problems.append((name, "引用缺失 %s" % label))

    print("skills: %d" % len(skills))
    if warns:
        print("WARN: %d（软约束，不失败）" % len(warns))
        for n, p in warns:
            print("  [%s] %s" % (n, p))
    if problems:
        print("PROBLEMS: %d" % len(problems))
        for n, p in problems:
            print("  [%s] %s" % (n, p))
        return 1
    print("RESULT: OK（frontmatter / name / description≤150 / H1 / references 链接全部通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
