#!/usr/bin/env python3
"""Regenerate main/fonts/font_zh_24.c from the UI source.

The character set is *derived from the C sources*, never hand-listed.  A hand
list is exactly how the verdict text "通过" ended up rendering as "通" plus a
tofu box: U+8FC7 was simply absent from the font.

Codepoints are handed to lv_font_conv as explicit `--range 0xXXXX,...` values
so the whole command line stays pure ASCII.  Git Bash converts non-ASCII argv
to UTF-16 using the console codepage, so `--symbols 通过...` would arrive
mangled.

Run:  python .workbuddy/tools/gen_font.py
Then: python .workbuddy/tools/check_font_coverage.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fontchars import source_chars as scan_source_chars   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main"
TOOLS = ROOT / ".workbuddy" / "tools"
NODE = Path("C:/Users/lx176/.workbuddy/binaries/node/versions/22.22.2-3/node.exe")
LV_FONT_CONV = TOOLS / "node_modules" / "lv_font_conv" / "lv_font_conv.js"
TTF = Path("C:/Windows/Fonts/simhei.ttf")
OUT = MAIN / "fonts" / "font_zh_24.c"

SIZE = 24          # px
BPP = 4            # 4bpp keeps the CJK font ~50 % smaller than 8bpp
ASCII_FIRST = 0x20
ASCII_LAST = 0x7E  # digits, letters, punctuation incl. '-'
GENERATED = {"font_zh_24.c"}   # never scan the generated file itself


def source_chars() -> tuple[set[int], dict[int, list[str]]]:
    """Every non-ASCII character a real string literal can put on screen."""
    where = scan_source_chars(MAIN, GENERATED)
    return set(where), where


def main() -> int:
    if not TTF.exists():
        print(f"missing font source: {TTF}")
        return 1
    if not LV_FONT_CONV.exists():
        print(f"missing lv_font_conv: {LV_FONT_CONV}")
        return 1

    chars, where = source_chars()
    if not chars:
        print("no non-ASCII string literals found -- refusing to write a font "
              "that cannot render the UI")
        return 1

    codes = sorted(chars)
    ranges = [f"0x{ASCII_FIRST:02X}-0x{ASCII_LAST:02X}"]
    ranges += [f"0x{c:04X}" for c in codes]

    cmd = [
        str(NODE), str(LV_FONT_CONV),
        "--font", str(TTF),
        "--range", ",".join(ranges),
        "--size", str(SIZE),
        "--bpp", str(BPP),
        "--format", "lvgl",
        "--no-compress",
        "--no-prefilter",
        "-o", str(OUT),
    ]

    print(f"symbols: {len(codes)} CJK/wide + ASCII 0x{ASCII_FIRST:02X}-0x{ASCII_LAST:02X}")
    for c in codes:
        print(f"  U+{c:04X}  {'/'.join(where[c])}")
    print("running lv_font_conv ...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return r.returncode

    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
