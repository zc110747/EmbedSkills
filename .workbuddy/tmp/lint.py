# -*- coding: utf-8 -*-
"""Skill 仓 frontmatter / 结构一致性校验，零依赖。"""
import os, re, sys

ROOT = r"D:/user_project/git/EmbedSkills"
DENY_DIR = {".git", ".workbuddy"}
problems = []
skills = []

for name in sorted(os.listdir(ROOT)):
    d = os.path.join(ROOT, name)
    if not os.path.isdir(d) or name in DENY_DIR:
        continue
    sp = os.path.join(d, "SKILL.md")
    if not os.path.isfile(sp):
        problems.append((name, "缺 SKILL.md"))
        continue
    txt = open(sp, encoding="utf-8", errors="replace").read()
    skills.append(name)
    if not txt.startswith("---"):
        problems.append((name, "无 frontmatter 起始 ---"))
        continue
    end = txt.find("\n---", 3)
    if end < 0:
        problems.append((name, "frontmatter 未闭合"))
        continue
    fm = txt[3:end]
    body = txt[end + 4:]
    m = re.search(r"^name:[ \t]*(.+)$", fm, re.M)
    if not m:
        problems.append((name, "frontmatter 缺 name"))
    elif m.group(1).strip() != name:
        problems.append((name, "name(%s) != 目录名" % m.group(1).strip()))
    m = re.search(r"^description:[ \t]*(.*)$", fm, re.M)
    if not m:
        problems.append((name, "frontmatter 缺 description"))
    else:
        L = len(m.group(1))
        if L == 0:
            problems.append((name, "description 为空"))
        elif L > 150:
            problems.append((name, "description %d>150" % L))
    if not re.search(r"^agent_created:[ \t]*true[ \t]*$", fm, re.M):
        problems.append((name, "缺 agent_created: true"))
    # 正文第一个非空行应为 H1
    first = ""
    for line in body.splitlines():
        if line.strip():
            first = line.strip()
            break
    if not first.startswith("# "):
        problems.append((name, "正文首行非 H1: %r" % first[:40]))
    # references 链接有效性：支持本 skill 相对引用与 `其他skill/references/x.md` 跨引用
    for owner, ref in set(re.findall(
            r"(?:([A-Za-z0-9_.\-]+)/)?references/([A-Za-z0-9_.\-]+\.md)", txt)):
        base = os.path.join(ROOT, owner) if owner and os.path.isdir(os.path.join(ROOT, owner)) else d
        if not os.path.isfile(os.path.join(base, "references", ref)):
            label = ("%s/references/%s" % (owner, ref)) if owner else ("references/%s" % ref)
            problems.append((name, "引用缺失 %s" % label))

print("skills: %d" % len(skills))
if problems:
    print("PROBLEMS: %d" % len(problems))
    for n, p in problems:
        print("  [%s] %s" % (n, p))
    sys.exit(1)
print("RESULT: OK（frontmatter / name / description / H1 / references 链接全部通过）")
