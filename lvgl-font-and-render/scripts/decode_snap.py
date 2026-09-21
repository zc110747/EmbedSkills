#!/usr/bin/env python3
"""Decode the DBGSCREEN dumps captured from the device console.

Input : a raw serial log containing one or more
            ===SNAP begin w=.. h=.. step=.. cols=.. rows=.. pal=..===
            P00=RRGGBB                     (up to 15 palette colours)
            R000:<one hex char per pixel>|<checksum>
            ===SNAP end===
        blocks emitted by main/dbg_screen.c
Output: one PNG per block, plus a summary of the TEXTFIT / GLYPH probes.

Encoding notes
  * a pixel is an index into the emitted palette, one hex character per pixel,
    so a full 800x480 frame is ~390 KB of ASCII instead of ~2.3 MB of RRGGBB
  * each row carries a checksum, chk = chk*31 + index over uint32, so a
    truncated or reordered transfer is caught instead of silently shifting
    the picture
  * the frame is emitted box-averaged by `step`, so the PNG is reconstructed
    at exactly the declared resolution by scaling the grid back up by `step`

Pure stdlib: PNG is written by hand (zlib + struct), no Pillow needed.

  python decode_snap.py dump.log frame.png          # every frame, frame_0.png ...
  python decode_snap.py dump.log frame.png 1        # just frame index 1
"""
from __future__ import annotations

import re
import struct
import sys
import zlib
from pathlib import Path

ANSI = re.compile(rb"\x1b\[[0-9;?]*[ -/]*[@-~]")
ROW = re.compile(r"^R(\d+):([0-9A-Fa-f]+)\|([0-9A-Fa-f]{8})$")
PAL = re.compile(r"^P(\d+)=([0-9A-Fa-f]{6})$")
HEAD = re.compile(r"w=(\d+) h=(\d+) step=(\d+) cols=(\d+) rows=(\d+) pal=(\d+)")


def write_png(path: Path, w: int, h: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)   # 8-bit truecolour RGB
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


class Frame:
    def __init__(self, w: int, h: int, step: int, cols: int, rows: int):
        self.w, self.h, self.step = w, h, step
        self.cols, self.rows = cols, rows
        self.pal: list[tuple[int, int, int]] = []
        self.glyph_rows: dict[int, list[int]] = {}
        self.bad = 0
        self.problems: list[str] = []


def parse(text: str) -> tuple[list[Frame], list[str], list[str]]:
    textfit: list[str] = []
    glyphs: list[str] = []
    frames: list[Frame] = []

    in_textfit = in_glyph = False
    cur: Frame | None = None
    expect_pal = 0

    for raw in text.replace("\r", "").split("\n"):
        ln = raw.strip()
        if not ln:
            continue

        if ln.startswith("===TEXTFIT begin"):
            in_textfit = True
            print(ln)
            continue
        if ln.startswith("===TEXTFIT end"):
            in_textfit = False
            print(ln)
            continue
        if ln.startswith("===GLYPH begin"):
            in_glyph = True
            print(ln)
            continue
        if ln.startswith("===GLYPH end"):
            in_glyph = False
            print(ln)
            continue
        if ln.startswith("===SNAP begin"):
            m = HEAD.search(ln)
            if not m:
                print(f"  !! unparsable SNAP header: {ln}")
                continue
            w, h, step, cols, rows, pal = map(int, m.groups())
            cur = Frame(w, h, step, cols, rows)
            expect_pal = pal
            frames.append(cur)
            print(ln)
            continue
        if ln.startswith("===SNAP end"):
            cur = None
            expect_pal = 0
            print(ln)
            continue
        if ln.startswith(("===DBGSCREEN", "===SNAP FAIL")):
            print(ln)
            continue

        if in_textfit:
            if ln.startswith("LABEL["):
                textfit.append(ln)
            elif "distinct" in ln:
                print("  " + ln)
            continue

        if in_glyph:
            if ln.startswith("GLYPH "):
                glyphs.append(ln)
            continue

        if cur is None:
            continue

        if expect_pal:
            m = PAL.match(ln)
            if m:
                v = int(m.group(2), 16)
                cur.pal.append(((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF))
                expect_pal -= 1
                continue
            print(f"  !! expected a palette line, got: {ln!r}")

        m = ROW.match(ln)
        if not m:
            continue
        idx, chars, chk = int(m.group(1)), m.group(2), int(m.group(3), 16)
        ix = [int(c, 16) for c in chars]

        calc = 0
        for v in ix:
            calc = (calc * 31 + v) & 0xFFFFFFFF
        if calc != chk:
            cur.bad += 1
            cur.problems.append(f"row {idx}: checksum {calc:08X} != {chk:08X}")
        if len(ix) != cur.cols:
            cur.bad += 1
            cur.problems.append(f"row {idx}: {len(ix)} px, expected {cur.cols}")
        cur.glyph_rows[idx] = ix

    return frames, textfit, glyphs


def render(f: Frame, png: Path) -> bool:
    if not f.glyph_rows:
        print(f"  {png.name}: no rows captured")
        return False
    if not f.pal:
        print(f"  {png.name}: no palette")
        return False

    gap = (255, 0, 255)                       # magenta = missing data
    black = (0, 0, 0)
    rows: list[bytes] = []

    for y in range(f.rows):
        ix = f.glyph_rows.get(y)
        if ix is None:
            line = [gap] * f.cols
        else:
            line = [f.pal[v] if v < len(f.pal) else black for v in ix]
            line += [gap] * (f.cols - len(line))
        big = b"".join(bytes(c) * f.step for c in line)
        rows.extend([big] * f.step)

    write_png(png, f.cols * f.step, f.rows * f.step, rows)
    missing = f.rows - len(f.glyph_rows)
    print(f"  {png.name}: {f.cols * f.step}x{f.rows * f.step}, "
          f"palette {len(f.pal)}, checksum errors {f.bad}, "
          f"missing rows {missing}")
    for p in f.problems[:5]:
        print("    !! " + p)
    return f.bad == 0 and missing == 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    log_path, png_path = Path(sys.argv[1]), Path(sys.argv[2])
    which = sys.argv[3] if len(sys.argv) > 3 else "all"

    text = ANSI.sub(b"", log_path.read_bytes()).decode("utf-8", "replace")
    frames, textfit, glyphs = parse(text)

    print("\n---- TEXTFIT ----")
    over = [t for t in textfit if "OVERFLOW" in t]
    print(f"labels measured: {len(textfit)}   overflow: {len(over)}")
    for t in over:
        print("  " + t)
    if not over and textfit:
        print("  no label overflows its cell")

    print("\n---- GLYPH ----")
    missing = [g for g in glyphs if "MISSING" in g]
    empty = [g for g in glyphs if "ink=0/" in g]
    inks = []
    for g in glyphs:
        m = re.search(r"ink=\d+/\d+ (\d+)%", g)
        if m:
            inks.append(int(m.group(1)))
    print(f"glyphs probed: {len(glyphs)}   missing: {len(missing)}   "
          f"zero-ink: {len(empty)}")
    if inks:
        print(f"ink coverage: min {min(inks)}%  max {max(inks)}%  "
              f"avg {sum(inks) / len(inks):.1f}%")
    for g in missing + empty:
        print("  " + g)

    print("\n---- SNAP ----")
    if not frames:
        print("no frame captured")
        return 1

    ok = True
    for i, f in enumerate(frames):
        if which != "all" and str(i) != which:
            continue
        out = (png_path if which != "all"
               else png_path.with_name(f"{png_path.stem}_{i}{png_path.suffix}"))
        ok &= render(f, out)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
