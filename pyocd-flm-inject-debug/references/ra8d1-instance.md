# 实例：Renesas RA8D1（R7FA8D1BH / Cortex-M85 / TrustZone）

通用机制见 SKILL.md；本文件只记**这块芯片的具体参数与专属坑**。换芯片时照此格式另写一份。

## 适用约束（决定必须走注入路径）

- pyOCD 0.45 **无** RA8D1 内建 target；OpenOCD 0.12（sysprogs）scripts/target 里**无 renesas/ra**。
- 未装 Renesas VSCode 扩展 / e2 studio / RFP；`pyocd pack install` 常因无 keil.com 网络失败。
- 调试器：板载 CMSIS-DAP（如 RTThread ART-Link，UID 形如 `0FEBxxxxxxxx`）。

## 关键事实：code flash 不在 0x0

RA8D1 是 TrustZone 布局，**code flash 起始 0x02000000**，因此通用 `cortex_m` target 的默认
memory map 里没有任何可写 flash。`connect_mode=pre-reset` 下能 halt、能读 CPUID
（`0x410FD232` = M85），但 `pyocd flash` / gdb `load` 无处落。

## 四个 FLM（缺一个就有一段烧不进去）

| 地址段 | FLM |
|---|---|
| `0x02000000` code flash | `RA8D1_2M.FLM` |
| `0x0300A100` 选项字节 | `RA8D1_CCONF.FLM` |
| `0x27000000` data flash | `RA8D1_DATA_C2M.FLM` |
| `0x27030080` data-flash 选项区 | `RA8D1_DCONF.FLM`（DevAdr `0x27030050`、szDev `0x3B0`） |

⚠️ `RA8D1_DCONF.FLM` 管哪段地址**在 DFP 的 pdsc 里查不到**，只能解析 FLM 内 `FlashDevice`
结构体：offset 132 = DevAdr(4B)、136 = szDev(4B)。

`pyocd_user.py` 里 flash region 的算法工作 RAM：`_RAMstart=0x22000000`、`_RAMsize=0x2000`。

> 本机已有成品可整目录复用：兄弟 RA8D1 工程的 `pyocd.yaml` / `pyocd_user.py` /
> `tools/flash/*.FLM` / `R7FA8D1BH.svd` 直接拷，无需重造。

## 构建（RT-Thread SCons + GCC ≥13）

```bash
RTT_CC=gcc RTT_EXEC_PATH="$(dirname "$(command -v arm-none-eabi-gcc)")" scons
```

- `rtconfig.py` 默认 `EXEC_PATH=C:\Users\XXYYZZ` 是占位符，必须靠 `RTT_EXEC_PATH` 覆盖，
  否则报 `toolchain path not exist`。
- SConstruct 在缺 `rt-thread`/`libraries` 软链时回退到 `../../../rt-thread` 与 `../libraries`，
  **不跑 mklinks 也能编**（`RTT_ROOT` 环境变量被 SConstruct 忽略，按 `os.path.exists` 重算）。
- gcc DEVICE 行 `-march=armv8.1-m.main+mve.fp+fp.dp` 配 `-mfpu=fpv5-sp-d16` 看似冲突，
  GCC 15.3 实测可通过；`BUILD=debug` 产物带 `-O0 -g` 才有源码级断点。

## 烧录实测

```bash
pyocd flash -t cortex_m --config pyocd.yaml -O connect_mode=pre-reset rtthread.elf
```

擦 ~296 KB / 写 ~267 KB，RC=0。芯片被锁（首次 SWD）时 `pre-reset` 已做预复位；
仍失败再考虑整片擦。

## headless 自测脚本（无 VSCode 验证整条链路）

```bash
pyocd gdbserver -t cortex_m --config pyocd.yaml -O connect_mode=pre-reset > /tmp/srv.log 2>&1 &
sleep 6
arm-none-eabi-gdb -batch -ex "set pagination off" -ex "file rtthread.elf" \
  -ex "target remote 127.0.0.1:3333" \
  -ex "monitor halt" -ex "info registers" \
  -ex "info address hal_entry" -ex "x/4xw 0x02000000" -ex "bt" \
  -ex "monitor reset halt" -ex "thbreak hal_entry" -ex "continue" \
  -ex "info registers pc" -ex "bt 12"
```

⚠️ **`target remote` 必须写 `127.0.0.1:3333`，不能写 `:3333`** —— 后者在 Windows 上触发
error 138「系统试图将驱动器合并到合并驱动器上的目录」，连不上。

通过判据：`monitor halt` 成功；`info address hal_entry` 给出地址；`thbreak hal_entry` 显示
`Hardware assisted breakpoint ... file src\hal_entry.c, line N`；`continue` 命中该行
（源码级断点 + 单步可用）。

## launch.json 差异点（相对 SKILL.md §3 的通用模板）

`targetId: cortex_m`、`runToEntryPoint: hal_entry`（不是 `main`）、`preLaunchTask: flash`
（先编后烧再连 GDB）、`svdFile: R7FA8D1BH.svd`。

## 反模式

- ❌ 指望 OpenOCD 0.12（sysprogs）调试 RA8D1：无 renesas/ra target 脚本。
- ❌ `pyocd pack install` 拉 RA8D1：多数环境无外网。
- ❌ 连 `:3333`：必须 `127.0.0.1:3333`。
- ❌ 以为要 mklinks 软链才能编：SConstruct 有回退。
