#!/usr/bin/env python3
"""
Extract text-with-coordinates and wire geometry from an Altium-exported schematic PDF.

Usage:
    python extract_schematic.py <input.pdf> <outdir>

Outputs into <outdir>:
    words.json       - per-page text tokens with bboxes
    wires.json       - per-page axis-aligned wire segments + component body boxes
    netlist.json     - reconstructed nets: {net_id: {"labels":[...], "nodes":[[x,y],...]}}
    pageN.png        - full-page render at 200 dpi
    crops/           - caller-driven; use crop_region() helper

Requires: pymupdf
"""
import json
import os
import re
import sys
import collections

try:
    import pymupdf
except ImportError:
    import fitz as pymupdf


SNAP_Q = 2.0        # grid snap quantum (pt)
TOL = 2.6           # node-merge tolerance (pt)
LABEL_TOL = 9.0     # max distance from label center to a wire node (pt)
PAGEBOX_MIN = 25    # min width of a box to be considered a component body
PAGEBOX_MIN_H = 18  # min height of a box to be considered a component body


def snap(v):
    return round(v / SNAP_Q) * SNAP_Q


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        r = x
        while self.p[r] != r:
            r = self.p[r]
        while self.p[x] != r:
            self.p[x], x = r, self.p[x]
        return r

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def collect_geometry(doc, page_no):
    """Return (lines, boxes) from vector drawings on a page."""
    p = doc[page_no]
    lines, boxes = [], []
    for dr in p.get_drawings():
        for item in dr['items']:
            if item[0] == 'l':
                a, b = item[1], item[2]
                lines.append(((a.x, a.y), (b.x, b.y)))
            elif item[0] == 're':
                r = item[1]
                boxes.append((r.x0, r.y0, r.x1, r.y1))
            elif item[0] == 'qu':
                pts = item[1]
                for i in range(4):
                    a, b = pts[i], pts[(i + 1) % 4]
                    lines.append(((a.x, a.y), (b.x, b.y)))
    return lines, boxes


def page_borders(boxes):
    """The outer drawing-frame rectangles, which must not be treated as component bodies."""
    out = []
    for (x0, y0, x1, y1) in boxes:
        w, h = abs(x1 - x0), abs(y1 - y0)
        # full-page frames are huge and span nearly the whole sheet
        if w > 700 and h > 500:
            out.append((x0, y0, x1, y1))
    return out


def body_boxes(boxes):
    frames = page_borders(boxes)
    out = []
    for (x0, y0, x1, y1) in boxes:
        w, h = abs(x1 - x0), abs(y1 - y0)
        if w > 700 and h > 500:
            continue
        if any(abs(x0 - f[0]) < 3 and abs(y0 - f[1]) < 3 for f in frames):
            continue
        if w > PAGEBOX_MIN and h > PAGEBOX_MIN_H:
            out.append((x0, y0, x1, y1))
    return out


def build_netlist(doc, page_no, words):
    """Union-find over wire segments; returns list of nets with node coords and labels."""
    lines, boxes = collect_geometry(doc, page_no)
    bodies = body_boxes(boxes)

    # only orthogonal segments are schematic wires
    axis = [(a, b) for (a, b) in lines
            if abs(a[0] - b[0]) < 0.6 or abs(a[1] - b[1]) < 0.6]

    # CRITICAL: drop any wire lying entirely inside a component body rectangle,
    # otherwise the whole symbol (e.g. an MCU outline) collapses into one net.
    def inside(seg, bx, pad=1.5):
        x0, y0, x1, y1 = bx
        return all(x0 - pad <= pt[0] <= x1 + pad and y0 - pad <= pt[1] <= y1 + pad
                   for pt in seg)

    wires = [s for s in axis if not any(inside(s, bx) for bx in bodies)]

    uf = UF()
    nodes = set()
    for (a, b) in wires:
        ka = (snap(a[0]), snap(a[1]))
        kb = (snap(b[0]), snap(b[1]))
        uf.union(ka, kb)
        nodes.add(ka)
        nodes.add(kb)
    nodes = sorted(nodes)

    # merge coincident / near-coincident endpoints
    for i, p in enumerate(nodes):
        for q in nodes[i + 1:]:
            if q[0] - p[0] > TOL:
                break
            if abs(q[1] - p[1]) <= TOL:
                uf.union(p, q)

    # T-junctions: a node lying on a wire's interior joins that wire's net
    for (a, b) in wires:
        ka = (snap(a[0]), snap(a[1]))
        kb = (snap(b[0]), snap(b[1]))
        for k in nodes:
            if k in (ka, kb):
                continue
            if abs(a[0] - b[0]) < 0.6:       # vertical
                if (abs(k[0] - ka[0]) <= TOL
                        and min(ka[1], kb[1]) - TOL <= k[1] <= max(ka[1], kb[1]) + TOL):
                    uf.union(ka, k)
            elif abs(a[1] - b[1]) < 0.6:     # horizontal
                if (abs(k[1] - ka[1]) <= TOL
                        and min(ka[0], kb[0]) - TOL <= k[0] <= max(ka[0], kb[0]) + TOL):
                    uf.union(ka, k)

    netpts = collections.defaultdict(list)
    for k in nodes:
        netpts[uf.find(k)].append(list(k))

    # attach text labels to the geographically nearest net
    flat = [(k, root) for root, ks in netpts.items() for k in ks]
    labels = collections.defaultdict(list)
    for w in words:
        t = w[4]
        cx, cy = (w[0] + w[2]) / 2.0, (w[1] + w[3]) / 2.0
        best, bd = None, 1e9
        for k, root in flat:
            dd = max(abs(k[0] - cx), abs(k[1] - cy))
            if dd < bd:
                bd, best = dd, root
        if best is not None and bd <= LABEL_TOL:
            labels[best].append(t)
    return netpts, labels


def crop_region(doc, page_no, outdir, name, x0, y0, x1, y1, dpi=700):
    """Render a region at high dpi. This is the most reliable way to read pin/net detail."""
    p = doc[page_no]
    pix = p.get_pixmap(dpi=dpi, clip=pymupdf.Rect(x0, y0, x1, y1))
    path = os.path.join(outdir, 'crops', f'{name}.png')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pix.save(path)
    return path


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    pdf_path, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    all_words, all_wires, all_nets = {}, {}, {}

    for i in range(doc.page_count):
        pg = f'page{i + 1}'
        p = doc[i]
        words = [list(w) for w in p.get_text('words')]
        all_words[pg] = words

        lines, boxes = collect_geometry(doc, i)
        bodies = body_boxes(boxes)
        axis = [(a, b) for (a, b) in lines
                if abs(a[0] - b[0]) < 0.6 or abs(a[1] - b[1]) < 0.6]

        def inside(seg, bx, pad=1.5):
            x0, y0, x1, y1 = bx
            return all(x0 - pad <= pt[0] <= x1 + pad and y0 - pad <= pt[1] <= y1 + pad
                       for pt in seg)

        wires = [s for s in axis if not any(inside(s, bx) for bx in bodies)]
        all_wires[pg] = {
            'wires': [[list(a), list(b)] for (a, b) in wires],
            'bodies': [list(b) for b in bodies],
        }

        netpts, labels = build_netlist(doc, i, words)
        nets = {}
        for n, (root, pts) in enumerate(netpts.items()):
            nets[f'net{n}'] = {'labels': sorted(set(labels.get(root, []))), 'nodes': pts}
        all_nets[pg] = nets

        pix = p.get_pixmap(dpi=200)
        pix.save(os.path.join(outdir, f'{pg}.png'))
        print(f'{pg}: words={len(words)} wires={len(wires)} bodies={len(bodies)} nets={len(nets)}')

    json.dump(all_words, open(os.path.join(outdir, 'words.json'), 'w'), ensure_ascii=False)
    json.dump(all_wires, open(os.path.join(outdir, 'wires.json'), 'w'), ensure_ascii=False)
    json.dump(all_nets, open(os.path.join(outdir, 'netlist.json'), 'w'), ensure_ascii=False)
    print(f'written to {outdir}')


if __name__ == '__main__':
    main()
