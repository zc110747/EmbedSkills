#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lint_bat.py — STM32 一键编译脚本 (build_oneclick.bat) 规范校验器

对应 stm32-build-and-scaffold / embedded-verification-acceptance 技能里的一键脚本规范。
在真正运行 .bat 之前先跑本脚本，主动拦截 `此时不应有 .` / `此时不应有 into。` 等
cmd 解析错误，避免双击/PowerShell 一跑就崩。

用法:
    python lint_bat.py                      # 默认递归扫描【当前目录】下的 build_oneclick.bat
    python lint_bat.py <path/to/build_oneclick.bat> [more .bat ...]
    python lint_bat.py --scan <dir>          # 递归扫描指定目录下所有 build_oneclick.bat
    python lint_bat.py --here                # 显式扫描当前目录（--self 为兼容别名）

退出码: 0 = 无 ERROR 级违规（含"没扫到文件"）; 1 = 存在 ERROR 级违规; 2 = 用法错误。

注：默认扫描目录就是 `os.getcwd()`，脚本内【不写死】任何本机路径或工程仓名。

==== 实测结论（2026-08-28, Win11 cmd）====
* 真正会崩的是【echo/@echo 文本里的特殊字符】(对应原"致命坑 3")：
    `(` 会开启命令组、`)` 会提前闭合父块、残留文本变成非法 token ->
    报 `此时不应有 .` / `此时不应有 into。`
* REM / :: 注释行里的 `( )` 实测【不会】崩，按 INFO 提示，不计入失败。
* `cd /d "%~dp0"` 与 `for` 块内 `2>&1`（原"致命坑 4"）在本机实测【不崩】
  （保留原始写法仍可编译通过），按 INFO 提示，不计入失败。
  -> 仅当路径含特殊字符且确证报错时再处理，避免无谓改动。

因此：只有 PIT3(echo) 与 PIT1 算 ERROR，其余为 INFO。
"""

import os
import sys
import glob
import re

TEXT_PREFIXES = ("echo", "rem", "@echo", "::")


def line_kind(line):
    """返回 ('echo'|'rem'|'other', stripped_without_prefix)"""
    s = line.lstrip()
    if s[:1] == "@":
        s = s[1:].lstrip()
    low = s.lower()
    for p in ("echo", "rem", "::"):
        if low.startswith(p):
            return ("echo" if p in ("echo",) else "rem"), s
    return "other", s


def lint_file(path):
    """返回违规列表 [(lineno, severity, pit_id, detail)]，severity: ERROR/INFO"""
    out = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError as e:
        return [(0, "ERROR", "IO", "cannot read: %s" % e)]

    depth = 0
    for i, raw in enumerate(lines, 1):
        line = raw.rstrip("\r")
        kind, stripped = line_kind(line)

        # 括号深度（只统计命令行，文本行忽略）
        if kind == "other":
            in_str = False
            for ch in line:
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    if depth > 0:
                        depth -= 1

        # ---- PIT1: echo 行里的 !VAR! 延迟展开打印 ----
        if kind == "echo" and re.search(r"![\w]+!", line):
            out.append((i, "ERROR", "PIT1",
                        "echo 行含 !VAR! 延迟展开打印（易变字面量）: " + stripped))

        # ---- PIT3: echo 文本里的特殊字符 & ( ) | < > ----
        if kind == "echo":
            bad = sorted(set(c for c in line if c in "&()|<>"))
            if bad:
                out.append((i, "ERROR", "PIT3",
                            "echo 行含危险字符 %s（会触发 此时不应有）: %s"
                            % ("".join(bad), stripped)))
        elif kind == "rem":
            bad = sorted(set(c for c in line if c in "&()|<>"))
            if bad:
                out.append((i, "INFO", "PIT3(rem)",
                            "REM 注释含 () 等（实测不崩，仅供参考）: " + stripped))

        # ---- PIT4a: cd 直接带 "%~dp0" ----
        if stripped.lower().startswith("cd") and "%~dp0" in line:
            out.append((i, "INFO", "PIT4a",
                        "cd 直接引用 %~dp0（本机实测不崩，仅供参考）: " + stripped))

        # ---- PIT4b: 括号块内 2>&1 ----
        if "2>&1" in line and depth > 0:
            out.append((i, "INFO", "PIT4b",
                        "括号块内 2>&1（本机实测不崩，仅供参考）: " + stripped))

    return out


USAGE = ("usage: python lint_bat.py [<file.bat> ...] [--scan <dir>] [--here]\n"
         "       (no arguments: scan the current directory recursively)")


def main(argv):
    targets = []
    scan_dirs = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--scan":
            i += 1
            if i >= len(argv):
                print("error: --scan needs a directory")
                print(USAGE)
                return 2
            scan_dirs.append(argv[i])
        elif a in ("--here", "--self"):
            # 显式扫描当前目录。不再写死任何本机路径 / 工程仓名。
            scan_dirs.append(os.getcwd())
        elif a in ("-h", "--help"):
            print(USAGE)
            return 0
        else:
            targets.append(a)
        i += 1

    # 默认：不带参数时扫描当前目录，避免内置一份"常见工程根"清单随人/随机器过期。
    if not targets and not scan_dirs:
        scan_dirs.append(os.getcwd())

    for d in scan_dirs:
        for f in glob.glob(os.path.join(d, "**", "build_oneclick.bat"), recursive=True):
            targets.append(f)

    if not targets:
        scope = ", ".join(scan_dirs) if scan_dirs else "."
        print("no build_oneclick.bat found under: %s" % scope)
        return 0

    err_files = 0
    err_total = 0
    for t in targets:
        v = lint_file(t)
        errs = [x for x in v if x[1] == "ERROR"]
        infos = [x for x in v if x[1] == "INFO"]
        if errs:
            err_files += 1
            err_total += len(errs)
            print("FAIL  %s" % t)
        else:
            print("PASS  %s" % t)
        for ln, sev, pid, det in v:
            loc = ("line %d" % ln) if ln else "file"
            print("      [%s] %s: %s" % (pid, loc, det))
    print("")
    print("summary: %d file(s), %d with ERROR-level violations, %d ERROR(s) total"
          % (len(targets), err_files, err_total))
    return 1 if err_files else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
