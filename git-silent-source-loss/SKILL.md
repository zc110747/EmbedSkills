---
name: git-silent-source-loss
description: 源文件凭空消失/换机编译不过：.gitignore 误匹配源文件 + git add 静默跳过。三步定位（check-ignore / log）、! 例外修复、类案清单。
agent_created: true
---
# git 静默吞源文件：`.gitignore` 误匹配 + `git add` 不报错

## 何时用

- 「**我没删过这个文件，但它不在仓库里**」/「别的机器 clone 下来就编不过」。
- `git add <被忽略的文件>` 返回 0、**没有任何提示**，但 `git status` 里看不到它。
- 报错关键词：
  - Go：`pattern ./...: directory prefix . does not contain main module or its selected dependencies`、
    `go.mod file not found in current directory or any parent directory`
  - CMake/编译器：`Cannot find source file: ...`、`No such file or directory` 指向一个「明明在磁盘上」的文件
  - 通用：`fatal: pathspec ... did not match any files`（不存在）vs **零输出**（存在但被忽略）
- 「我机器上能编，同事机器编不过」的仓库级版本。

## 核心机制（必须先理解，否则修不对）

两个设计叠加成了这个坑：

1. `.gitignore` 是**全局通配**匹配。一条为「Fortran 模块文件」写的 `*.mod`，同时匹配 Go 的 `go.mod`；
   一条为「构建产物」写的 `Build/`，在同一仓库里可能正好是源码目录名。
2. `git add` 遇到被忽略的路径是**静默 no-op**：不报错、不警告、退出码 0。
   于是「我 add 过了」是幻觉，`git commit` 也不会把它带上。

**最恶性的后果是「一半提交」**：同目录下 `.gitignore` 只吃掉一个文件时，会出现
`go.sum` 已入库、`go.mod` 从未入库 这种组合。作者本机因为文件仍在磁盘上（只是未跟踪），
一切正常；**任何时候重新 clone，编译立刻全挂**。

## 三步定位法（10 秒内定性）

```bash
# 1) 这个文件到底是不是被忽略了？（有输出 = 被忽略，并打印 规则所在文件:行号:规则）
git check-ignore -v path/to/file

# 2) 它是不是**从未**被提交过？（--diff-filter=A = 只看「被添加」的提交）
#    无输出 = 历史上从来没有这个文件 -> 不是「被误删」，是「从未 add 成功」
git log --all --diff-filter=A --name-only -- '**/file'

# 3) 还有没有别的文件同病？（列出现存但被忽略的条目，再排除真正的构建产物）
git status --ignored --short | grep '^!!'
```

> 判定「被改动/回退」只认 `git diff` / `git status --short`，**不要用 grep 计数**。

## 修复

1. **补回文件**。Go 工程可以只靠 `go.sum` + 模块缓存重建：
   ```bash
   cd <module-root>
   # 写最小 go.mod（module + go 指令 + 直接依赖），然后
   go mod tidy            # 由 go.sum / 模块缓存补全全部间接依赖并收敛 go.sum
   go build ./... && go test ./...
   ```
   重建时**优先对齐模块缓存里已有的版本**（`ls $(go env GOMODCACHE)/<mod>@v*`），
   否则离线环境或私有代理下会拉不到。
2. **改 `.gitignore`，并把「为什么不能加回来」写进注释**——否则下一个人会「顺手」再加一次：
   ```gitignore
   # Fortran module files.
   # NOTE: do NOT re-add a bare '*.mod' pattern here. It also matches Go's
   # go.mod, and git then skips it silently on 'git add'.
   *.smod
   !go.mod
   ```
3. **确认修复生效**：`git check-ignore -v <path>` 必须**不再有输出**（exit 1），
   且 `git status --short <path>` 显示 `??` / `A`（而不是什么都不显示）。

## 类案清单（同一根因的不同马甲）

| `.gitignore` 规则 | 被误伤的源文件 | 备注 |
|---|---|---|
| `*.mod` | **`go.mod`** | 本 skill 的标准案例；`*.smod` 才是真正想写的 |
| `*.log` / `*.tmp` | 需要入库的日志样例、测试夹具 | 夹具被吃掉 → 测试在别人机器上静默 skip |
| `Makefile` | 手写的构建入口 | 一加就丢，且完全无提示 |
| `Build/` `build/` `build-*/` | 名字就叫 build 的**源码目录** | Windows 大小写不敏感，小写同样中招 |
| `Drivers/` `third_party/` | 厂商 SDK 源码目录 | 常见于「顺手抄来的 STM32 .gitignore」 |
| `*.a` `*.lib` `*.dll` | 必须随仓库分发的小体积静态库 | 预编译组件消失 |
| `Debug/` `Release/` | 同名源码/脚本目录 | 同上，「顺手抄来的」模板 |

> 复用的 `.gitignore` 模板（尤其中文嵌入式圈子里流传的 STM32/Keil 版本）是这类事故的高发源。
> **新建目录/新增文件类型前先探针**：`git check-ignore -v <新路径>/probe.txt`。

## 判据 / 自检

- 修完立刻：`git status --short` 必须能看到该文件（`??` → `git add` → `A`）。
- 端到端判据是**重新 clone 到临时目录后能不能构建**，不是「本机能编过」——
  本机能编过恰恰是这个 bug 的默认状态，它**证明不了任何事**。
- 只读/只判断阶段（如排查任务）：只用第 1 步的三条只读命令，**不要动工作区**。

## 坑

- **`git add` 的静默性是设计行为，不是 bug**，所以没有任何「忽略告警」可以指望；
  唯一可靠的动作是主动跑 `git check-ignore -v`。
- Windows 上 `git check-ignore -v` 的输出路径用 `/` 分隔、`\` 也能识别；**用绝对或仓库相对路径均可**，
  但**传目录**只会判定目录本身，不递归告诉你里面哪些文件被忽略——要逐文件探。
- Git Bash 里 `taskkill /F` 之类带 `/X` 的参数会被 MSYS 当路径转换成 `F:/`，
  需要 `MSYS_NO_PATHCONV=1` 前缀。查「哪个进程占着文件」时容易撞上。
