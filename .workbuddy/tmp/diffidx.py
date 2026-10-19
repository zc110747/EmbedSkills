# -*- coding: utf-8 -*-
import os, re
ROOT = r"D:/user_project/git/EmbedSkills"
tbl = open(os.path.join(ROOT, "STM32_skills_能力表.md"), encoding="utf-8").read()
listed = set(re.findall(r"^\| `([A-Za-z0-9_.\-]+)`", tbl, re.M))
real = {n for n in os.listdir(ROOT)
        if os.path.isdir(os.path.join(ROOT, n)) and not n.startswith(".")
        and os.path.isfile(os.path.join(ROOT, n, "SKILL.md"))}
print("表内 %d / 实际 %d" % (len(listed), len(real)))
print("缺（实际有、表里没）:", sorted(real - listed))
print("多（表里有、实际没）:", sorted(listed - real))
