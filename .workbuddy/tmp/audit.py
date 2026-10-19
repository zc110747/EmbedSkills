import os, re, sys

ROOT = r"D:/user_project/git/EmbedSkills"
DENY = {"README.md", ".git", ".workbuddy", "sync_skills.sh"}

def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()

rows = []
for name in sorted(os.listdir(ROOT)):
    d = os.path.join(ROOT, name)
    if not os.path.isdir(d) or name in DENY:
        continue
    sp = os.path.join(d, "SKILL.md")
    if not os.path.isfile(sp):
        rows.append((name, -1, -1, -1, 0, 0, "MISSING-SKILL.md"))
        continue
    txt = read(sp)
    m = re.search(r"^description:\s*(.*)$", txt, re.M)
    desc = m.group(1).strip() if m else ""
    body = len(txt) - (m.end() if m else 0)
    refs = 0
    refdir = os.path.join(d, "references")
    if os.path.isdir(refdir):
        for f in os.listdir(refdir):
            if f.endswith(".md"):
                refs += 1
    scripts = 0
    sdir = os.path.join(d, "scripts")
    if os.path.isdir(sdir):
        scripts = len([f for f in os.listdir(sdir) if os.path.isfile(os.path.join(sdir, f))])
    rows.append((name, len(desc), body, len(txt.splitlines()), refs, scripts, ""))

rows.sort(key=lambda r: -r[1])
print("skill | desc字符 | 正文B | 行数 | refs | scripts")
for r in rows:
    flag = "  <<< 超150" if r[1] > 150 else ""
    print(f"{r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]}{flag}")

over = [r for r in rows if r[1] > 150]
total = sum(r[1] for r in rows if r[1] > 0)
print(f"\n合计 {len(rows)} skill, desc 总字符 {total}")
print(f"超 150 字符: {len(over)} 篇 -> {[ (r[0], r[1]) for r in over ]}")
print(f"正文 >6KB: {[(r[0], r[2]) for r in rows if r[2] > 6144]}")
