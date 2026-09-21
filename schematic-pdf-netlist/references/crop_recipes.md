# 裁剪与交叉校验配方

供读取 EDA 导出原理图 PDF 时直接粘贴的片段。约定 `PY` = 受管 venv 的 python，`OUT` = 提取脚本的输出目录。

## 1. 定位某个器件的坐标

先知道 refdes 落在哪，再决定裁剪哪块。

```python
import json
d = json.load(open(f'{OUT}/words.json'))
for w in d['page1']['words']:
    if any(w[4] == c or w[4].startswith(c) for c in ('U7', 'K1', 'J2')):
        print(f'{w[0]:7.1f} {w[1]:7.1f} {w[2]:7.1f} {w[3]:7.1f}  {w[4]}')
```

文字记录布局 `[x0, y0, x1, y1, text, block_no, line_no, word_no]`，单位为 PDF 点，原点左上，y 向下增长。

## 2. 把矩形内的 token 全倒出来（找功能块最快的方式）

```python
import json
d = json.load(open(f'{OUT}/words.json'))
X0, Y0, X1, Y1 = <块左上x>, <块左上y>, <块右下x>, <块右下y>
for w in sorted(d['page1']['words'], key=lambda w: (round(w[1]/4), w[0])):
    if X0 <= w[0] and w[2] <= X1 and Y0 <= w[1] and w[3] <= Y1:
        print(f'{w[0]:7.1f} {w[1]:7.1f}  {w[4]}')
```

## 3. 按区域批量裁剪成可读图块

```python
import pymupdf, os
doc = pymupdf.open('schematic.pdf')
os.makedirs('crops', exist_ok=True)
p = doc[0]
regions = {                                  # 用第 1、2 步定出的坐标填空
    '<block_a>': (x0, y0, x1, y1),
    '<block_b>': (x0, y0, x1, y1),
}
for name, (x0, y0, x1, y1) in regions.items():
    pix = p.get_pixmap(dpi=700, clip=pymupdf.Rect(x0, y0, x1, y1))
    pix.save(f'crops/{name}.png')
    print(name, pix.width, pix.height)
```

等价的内置助手：`scripts/extract_schematic.py` 的 `crop_region(doc, page_no, outdir, name, x0, y0, x1, y1, dpi=700)`。

### dpi 取值

| 用途 | dpi |
|---|---|
| 整页布局普查 | 200 |
| 块级阅读、脚号可辨 | 600 |
| 紧贴细节（脚号 + net 名 + NC 叉） | 900 |

超大裁剪（例如四分之一页开到 900 dpi）可能超出 Read 工具接受的图像尺寸；裁剪图读不出来时降到 600 dpi 或缩小矩形。

## 4. 全页搜索某个网络标签的位置

```python
import json
d = json.load(open(f'{OUT}/words.json'))
NEEDLE = '<net-name>'
for pg in d:
    for w in d[pg]['words']:
        if NEEDLE in w[4]:
            print(f"{pg}  {w[0]:7.1f} {w[1]:7.1f}  {w[4]}")
```

## 5. 交叉校验：几何 net ↔ 已读块

按标签丰富度列出所有带标签的 net。标签多的（5 个以上）是总线 / 电源轨；带 2~4 个标签的是应在裁剪图里读到的信号网。

```python
import json
d = json.load(open(f'{OUT}/netlist.json'))
pg = 'page1'
for nid, net in sorted(d[pg].items(), key=lambda kv: -len(kv[1]['labels'])):
    labs = [l for l in net['labels'] if not l.startswith(('PI', 'CO'))]   # 剥掉焊盘标注
    if not labs:
        continue
    print(f"{nid}  {len(net['nodes']):4d}pts  {' | '.join(sorted(labs))}")
```

两边对账：几何侧有、裁剪图里没读到的 net 要回头补看；裁剪图里读到、几何侧没有的 net 说明重建漏了连接。

## 6. Windows / Git Bash 环境坑

- 不要在 Git Bash 里跑 `timeout N cmd`：会解析到 `System32\TIMEOUT.EXE`（Windows 的空闲超时工具），报「默认选项不允许超过 '1' 次」。依赖工具自身的超时即可。
- `sort -u` 会解析到 `System32\sort.exe`，不支持 `-u` 且返回空。改用 `awk '!seen[$0]++'` 或 `/usr/bin/sort`。
- 裸 `bash script.sh` 可能命中 WSL 启动器（`System32\bash.exe`），改用 `/usr/bin/bash` 或 `sh`。
- 产物写在工程目录内，不要写 `/tmp`，可能不持久。
