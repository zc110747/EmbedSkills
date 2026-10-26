#!/usr/bin/env python3
"""Shared character-set extraction for the LVGL subset-font toolchain.

Both gen_font.py (which builds the font) and check_font_coverage.py (which
asserts the built font can render the UI) have to agree on what "the UI can
print" means.  If they drift apart the guard silently stops guarding, so the
scan lives here once and both import it.

The scan deliberately ignores comments.  A doc comment that quotes the spec
(`/* "默认都为空，读取失败才为(-)" */`) is prose, not UI text -- counting it
pulls glyphs nobody can ever see into the font and inflates it by ~40 %.
"""
from __future__ import annotations

import re
from pathlib import Path

LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')


def strip_comments(src: str) -> str:
    """Drop C block and line comments, leaving string literals intact."""
    out: list[str] = []
    i, n = 0, len(src)

    while i < n:
        c = src[i]

        # copy a literal verbatim, honouring backslash escapes
        if c in ('"', "'"):
            quote = c
            out.append(c)
            i += 1
            while i < n:
                out.append(src[i])
                if src[i] == "\\" and i + 1 < n:
                    out.append(src[i + 1])
                    i += 2
                    continue
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            continue

        if c == "/" and src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue

        if c == "/" and src.startswith("//", i):
            end = src.find("\n", i + 2)
            i = n if end < 0 else end
            continue

        out.append(c)
        i += 1

    return "".join(out)


def source_chars(main_dir: Path, generated: set[str]) -> dict[int, list[str]]:
    """Every non-ASCII codepoint appearing in a real string literal.

    Returns codepoint -> sorted list of files that use it, so callers can
    report *where* a missing glyph comes from.
    """
    found: dict[int, list[str]] = {}

    for path in sorted(list(main_dir.rglob("*.c")) + list(main_dir.rglob("*.h"))):
        if path.name in generated:
            continue  # never scan the generator's own output

        text = strip_comments(path.read_text(encoding="utf-8"))
        for lit in LITERAL.findall(text):
            for ch in lit:
                if ord(ch) > 0x7F:
                    files = found.setdefault(ord(ch), [])
                    if path.name not in files:
                        files.append(path.name)

    return found
