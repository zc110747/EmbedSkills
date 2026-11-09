# 追加重定向截断与文件恢复

## 1. 症状：内容在，开头丢了

在 Git Bash 里用 `cat >> file <<'EOF' ... EOF` 追加，命令**成功返回、无任何报错**，
事后 `grep` / `wc -l` **也能看到新内容**——但目标文件的**开头被新内容覆盖**，原文头部静默丢失。

实测（两份不同文件复现）：

| 现象 | 原文 | 追加后 | 后果 |
|---|---|---|---|
| 大小不变 | 14342 B | **仍是 14342 B** | 标题 + 前 5 节被覆盖 |
| 大小不变 | 8386 B | **仍是 8386 B** | 开头若干章节被覆盖 |

写入被落在偏移 0，覆盖了等长区间，所以文件长度**正好不变**。

## 2. 判定：追加前后比大小

正常追加 ⇒ 文件必然**变大**；**大小不变 = 中招**。

```bash
before=$(stat -c%s f.md); cat >> f.md <<'EOF'
...
EOF
after=$(stat -c%s f.md); [ "$after" -gt "$before" ] || echo "⚠️ 追加未生效/被覆盖"
```

## 3. 正确做法（按优先级）

1. **一律用 Write / Edit 工具**改文件，不用 shell 重定向。
2. 必须追加时用 **Python 二进制模式**并断言增长：

```python
import pathlib
def append_binary(target, frag, crlf=False):
    t = pathlib.Path(target); before = t.stat().st_size
    data = pathlib.Path(frag).read_bytes()
    if crlf: data = data.replace(b'\n', b'\r\n')   # 目标为 CRLF 时保持一致
    with open(target, 'ab') as f: f.write(data)
    after = t.stat().st_size
    assert after > before, f'追加未增长: {before} -> {after}'
```

> 先 Write 一个临时片段文件，再用它追加，最后删片段。
> `crlf=True` 用于 CRLF 目标；`sed -i` 会剥掉行尾，别用它改这类文件。

## 4. 同族坑

- **同一文件的两处 Edit 不要放在同一条消息**：并行执行会互相覆盖，其中一处被静默吞掉。
  改完必须复核内容，不要相信 "Successfully edited"。
- **`old_string` 只命中标题行时，新内容里要把标题补回去**，否则标题被吃掉。
- 沙箱内 `rm -rf` / `for` 循环串多个目录会被 SIGTERM（stdout 一起丢）
  ⇒ `find <dir> -depth -delete`，一次一个目录、分多次调用。

## 5. 救援：逐版本快照

文件被误覆盖/误删时**先别重写**：宿主保留每个文件的逐版本快照。

```
~/.workbuddy/file-history/<project-uuid>/<content-hash>@vN
```

```bash
# 1) 用正文里唯一的特征串定位所有历史版本
grep -rl "唯一特征串" ~/.workbuddy/file-history/ | head

# 2) 快照名不含原文件名 ⇒ 用原始字节数对齐版本号
ls -la ~/.workbuddy/file-history/<uuid>/ | grep "<原始字节数>"

# 3) 校验候选：UTF-8 可解码 + 关键锚点齐全 + 行尾统计一致
python -c "
import pathlib
b=pathlib.Path('candidate@vN').read_bytes()
print(len(b), b.count(bytes([13,10])))
t=b.decode('utf-8'); print(t.find('# 标题'), t.find('## D1'), t.find('## D17'))"

# 4) 覆盖回去，再用 §3 的安全方式重做
cp ~/.workbuddy/file-history/<uuid>/<hash>@v4 docs/decisions.md
```

其它可能有用的目录：`changes-index/`、`changes-detail/`、`blobs/`、`shell-snapshots/`、`sessions/`。

> ⚠️ 快照是**文件级**的，不含版本时间语义；同 size 的多个版本要逐个打开比对锚点。
