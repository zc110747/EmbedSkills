#!/usr/bin/env python3
"""Fail if font_zh_24.c cannot render every character the UI can print.

This is the offline guard for the bug the on-device probe caught: the font had
73 CJK glyphs but not U+8FC7 (过), so the verdict cells rendered as
"通" + a tofu box, silently.  Run it after any change to a UI string, or wire
it into the build.

  python .workbuddy/tools/check_font_coverage.py     # exit 0 = covered

It parses the generated lv_font_fmt_txt_cmap_t table straight out of the C
file, so it validates the artefact that actually gets linked, not the
generator's intent.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fontchars import source_chars as scan_source_chars   # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "main"
FONT_C = MAIN / "fonts" / "font_zh_24.c"
GENERATED = {"font_zh_24.c"}

# one lv_font_fmt_txt_cmap_t initialiser, as lv_font_conv writes it
CMAP = re.compile(
    r"\.range_start\s*=\s*(\d+),\s*\.range_length\s*=\s*(\d+),\s*"
    r"\.glyph_id_start\s*=\s*\d+,\s*\.unicode_list\s*=\s*(\w+),"
)
# the unicode_list_N[] arrays themselves, which sit above the cmap table
UINT16_ARRAY = re.compile(r"\b(unicode_list_\d+)\[\]\s*=\s*\{(.*?)\};", re.S)


def source_chars() -> dict[int, list[str]]:
    """Same scan the generator uses, comments excluded (see fontchars.py)."""
    return scan_source_chars(MAIN, GENERATED)


def font_coverage() -> tuple[set[int], int]:
    text = FONT_C.read_text(encoding="utf-8")

    arrays: dict[str, list[int]] = {}
    for name, body in UINT16_ARRAY.findall(text):
        arrays[name] = [int(v, 16) for v in re.findall(r"0x([0-9a-fA-F]+)", body)]

    covered: set[int] = set()
    for start, length, ulist in CMAP.findall(text):
        start, length = int(start), int(length)
        if ulist == "NULL":
            # LV_FONT_FMT_TXT_CMAP_FORMAT0_TINY: dense, one glyph per codepoint
            covered.update(range(start, start + length))
        else:
            # LV_FONT_FMT_TXT_CMAP_SPARSE_TINY: unicode_list holds *offsets*
            # from range_start, not the codepoints themselves.
            for off in arrays.get(ulist, []):
                covered.add(start + off)

    return covered, len(covered)


def main() -> int:
    if not FONT_C.exists():
        print(f"FAIL: {FONT_C} does not exist -- run gen_font.py")
        return 1

    needed = source_chars()
    covered, n = font_coverage()

    missing = {c: f for c, f in needed.items() if c not in covered}

    print(f"font glyphs parsed : {n}")
    print(f"chars used by source: {len(needed)}")

    if not missing:
        print("PASS: every character used by the UI has a glyph")
        return 0

    print(f"FAIL: {len(missing)} character(s) would render as tofu:")
    for c in sorted(missing):
        print(f"  U+{c:04X} '{chr(c)}'  used in {'/'.join(missing[c])}")
    print("regenerate with: python .workbuddy/tools/gen_font.py")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
