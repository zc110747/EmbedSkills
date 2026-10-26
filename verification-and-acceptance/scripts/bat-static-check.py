"""Static contract checks for a Windows .bat launcher.

Why this exists: cmd.exe cannot be *reliably* driven from every agent environment, and the
checks below are the ones that catch real breakage without running anything. It is not a
substitute for running the script -- it cannot see semantics (see check 10, which is a
heuristic for exactly one class of semantic bug). It is the cheap gate you run on every edit,
then you run the script for real.

Usage:
    python bat-static-check.py PATH\\TO\\script.bat [--fix] [--subroutine-marker :name]

    --fix               convert LF line endings to CRLF in place
    --subroutine-marker label after which `exit /b` is expected and must NOT pause
                        (default: auto -- the last label in the file)

Exit status 0 when everything passes, 1 otherwise, so it can gate a build.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------------- arguments

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BAT = Path(args[0])
FIX = "--fix" in sys.argv
MARKER = None
for i, a in enumerate(sys.argv):
    if a == "--subroutine-marker" and i + 1 < len(sys.argv):
        MARKER = sys.argv[i + 1].lower()

raw = BAT.read_bytes()
text = raw.decode("utf-8", errors="replace")
lines = text.splitlines()

checks: list[tuple[str, bool, str]] = []


def ck(label: str, ok: bool, detail: str = "") -> None:
    checks.append((label, bool(ok), "" if ok else str(detail)))


# ------------------------------------------------------------------- 1. CRLF line endings

bare_lf = raw.count(b"\n") - raw.count(b"\r\n")
if FIX and bare_lf:
    fixed = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    BAT.write_bytes(fixed.encode("utf-8"))
    raw = BAT.read_bytes()
    bare_lf = raw.count(b"\n") - raw.count(b"\r\n")
ck("every newline is CRLF", bare_lf == 0,
   f"{bare_lf} bare-LF line(s); LF-only .bat makes cmd fragment the file and can break labels")

# ------------------------------------------------------------------- 2. pure ASCII

non_ascii = sorted({b for b in raw if b > 127})
ck("file is pure ASCII (GBK console contract)", not non_ascii, f"non-ASCII bytes: {non_ascii[:12]}")

# ------------------------------------------------------------------- 3. no UTF-8 BOM

ck("no UTF-8 BOM", not raw.startswith(b"\xef\xbb\xbf"))

# ------------------------------------------------------------------- 4/5. label integrity

code_lines = [ln for ln in lines if not re.match(r"^\s*(rem\b|::)", ln, re.I)]
labels = {m.group(1).lower() for m in re.finditer(r"^\s*:([A-Za-z_]\w*)", text, re.M)}
# `goto` is normally preceded by `if ...`, so this must not be anchored to line start.
refs = {m.group(1).lower()
        for ln in code_lines
        for m in re.finditer(r"(?:^|\s)(?:goto|call)\s+:([A-Za-z_]\w*)", ln, re.I)}
ck("every goto/call target exists", not (refs - labels), sorted(refs - labels))
ck("no unreferenced labels", not (labels - refs), sorted(labels - refs))

# ------------------------------------------------------------------- 6. ordering of labels
# The subroutine region is what you `call`, not what you `goto`: a `goto` target is part of the
# main flow and its exits must pause, while a `call` target returns to its caller and must not.
# Taking "the last label in the file" gets this wrong as soon as a script has more than one
# subroutine, which is how this heuristic was caught.

label_order = [m.group(1).lower() for m in re.finditer(r"^\s*:([A-Za-z_]\w*)", text, re.M)]
called = {m.group(1).lower()
          for ln in code_lines
          for m in re.finditer(r"(?:^|\s)call\s+:([A-Za-z_]\w*)", ln, re.I)}

if MARKER:
    marker = MARKER.lstrip(":").lower()
else:
    marker = next((name for name in label_order if name in called), None)

main_lines, sub_lines = lines, []
if marker and marker in label_order:
    cut = next(i for i, ln in enumerate(lines) if ln.strip().lower() == f":{marker}")
    main_lines, sub_lines = lines[:cut], lines[cut:]

# ------------------------------------------------------------------- 7. pause before exit
# Contract: every path that ends the script pauses first. Subroutines end with `exit /b` on
# purpose and must NOT pause -- they return to the caller.

unpaused = []
for i, ln in enumerate(main_lines):
    if not re.match(r"^exit\s*/b", ln.strip(), re.I):
        continue
    window = []
    for back in range(i - 1, -1, -1):
        if re.match(r"^:[A-Za-z_]", main_lines[back].strip()):
            break
        window.append(main_lines[back].strip().lower())
    if "pause" not in window:
        unpaused.append((i + 1, ln.strip()))
ck("every main-flow exit /b is preceded by pause in its block", not unpaused, unpaused)

# ------------------------------------------------------------------- 8. no tail fall-through

meaningful = [ln for ln in lines if ln.strip()]
last_stmt = meaningful[-1].strip() if meaningful else ""
ck("file's final statement is an exit /b", re.match(r"^exit\s*/b", last_stmt, re.I), repr(last_stmt))
if sub_lines:
    stmts = [ln.strip() for ln in sub_lines
             if ln.strip() and not ln.strip().lower().startswith("rem")]
    ck(f"subroutine :{marker} ends with exit /b",
       re.match(r"^exit\s*/b", stmts[-1], re.I) if stmts else False,
       stmts[-1] if stmts else "<empty>")

# ------------------------------------------------------------------- 9. quote balance

unbalanced = [(i + 1, ln) for i, ln in enumerate(lines) if ln.count('"') % 2]
ck("every line has balanced double quotes", not unbalanced, unbalanced[:3])

# ------------------------------------------------------------------- 10. interpolation == execution
# The one heuristic here, and the bug that motivated this file. cmd re-parses a line *after*
# variable expansion, so `echo ... %V%` with V containing a separator does not print V -- it
# prints the first half and executes the rest, in the script's own working directory.
SEPARATORS = ("&&", "||", "|", ">", "<", "&")


def separator_carrying_vars() -> dict[str, str]:
    found: dict[str, str] = {}
    for ln in code_lines:
        m = re.match(r'^\s*set\s+"?([A-Za-z_]\w*)=(.*?)"?\s*$', ln, re.I)
        if not m:
            continue
        name, value = m.group(1), m.group(2)
        if any(sep in value for sep in SEPARATORS):
            found[name.lower()] = value
    return found


risky = separator_carrying_vars()
offenders = [
    (i + 1, ln.strip()) for i, ln in enumerate(code_lines)
    if re.match(r"^\s*echo\b", ln, re.I)
    and any(re.search(rf"%{re.escape(name)}%", ln, re.I) for name in risky)
]
ck("no echo interpolates a variable that can hold a separator", not offenders,
   f"risky vars {sorted(risky)}; offending lines {offenders}")

# ------------------------------------------------------------------- report

failed = [c for c in checks if not c[1]]
for label, ok, detail in checks:
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"   -> {detail}" if detail else ""))
print()
print(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
if risky:
    print(f"note: variables carrying separators (only safe inside quotes): {sorted(risky)}")
sys.exit(1 if failed else 0)
