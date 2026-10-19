import os, re, sys, json

ROOT = r"D:/user_project/git/EmbedSkills"
names = sys.argv[1:]
for n in names:
    p = os.path.join(ROOT, n, "SKILL.md")
    t = open(p, encoding="utf-8", errors="replace").read()
    m = re.search(r"^description:[ \t]*(.*)$", t, re.M)
    d = m.group(1) if m else "<NONE>"
    print("### %s  (%d chars)" % (n, len(d)))
    print(d)
    print()
