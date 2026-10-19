---
name: ra8d1-vscode-pyocd-debug
description: VSCode 对 RA8D1（R7FA8D1BH）做源码级调试：pyOCD 无 target 时的绕过路径与 launch.json 配置。触发：RA8D1 调试、pyocd no matching devices、OpenOCD 无 renesas target、cortex-debug。
agent_created: true
---

# RA8D1 VSCode 仿真调试（pyOCD 通用 cortex_m + 内存映射注入）

## 适用场景
- 芯片：Renesas RA8D1（R7FA8D1BH，Cortex-M85，含 MVE/TrustZone）。
- 调试器：板载 CMSIS-DAP（如 RTThread ART-Link，UID 形如 0FEBxxxxxxxx）。
- 约束：pyOCD 0.45 无 RA8D1 内置 target；OpenOCD 无 RA 支持；没装 Renesas VSCode 扩展 / e2 studio / RFP；且可能无网络拉 DFP（`pyocd pack` 被墙）。

## 核心思路（为什么能成）
RA8D1 的 TrustZone 布局：**code flash 在 0x02000000**（不是 0x00000000），所以 pyOCD 通用 `cortex_m` 的默认内存映射里没有可写 flash，`pyocd flash`/gdb `load` 无处落。解法是：
1. 用 `target_override: cortex_m`（pyOCD 能连上 CMSIS-DAP 并 halt 读 CPUID=0x410FD232=M85）。
2. 用 `pyocd_user.py` 的 `will_init_target` 钩子把 RA8D1 内存映射（含 flash region + FLM 算法路径）注入进去。
3. flash 算法用 Renesas RA_DFP 的 4 个 `.FLM`（code_flash / code_flash_config / data_flash / data_flash_config），放到 `tools/flash/`。

> 本机已有成品可整目录复用：兄弟 RA8D1 工程（如 `projects/vision_board_camera`）的 `pyocd.yaml` / `pyocd_user.py` / `tools/flash/*.FLM` / `R7FA8D1BH.svd` 直接拷过来即可，无需重新造。

## 需要的文件（工程根）
- `pyocd.yaml`：`target_override: cortex_m` + `frequency: 1000000`。
- `pyocd_user.py`：见下方模板（FlashRegion + `_RAMstart=0x22000000,_RAMsize=0x2000` 给算法做工作 RAM）。
- `tools/flash/RA8D1_2M.FLM`、`RA8D1_CCONF.FLM`、`RA8D1_DATA_C2M.FLM`、`RA8D1_DCONF.FLM`（来自 Renesas RA_DFP）。
- `R7FA8D1BH.svd`（外设视图，Cortex-Debug 用）。
- `build.bat`：RT-Thread SCons 封装，`RTT_CC=gcc`，从 PATH 自动探测 `arm-none-eabi-gcc` 填 `RTT_EXEC_PATH`。
- `.vscode/launch.json`：cortex-debug，`servertype: pyocd`，`targetId: cortex_m`，`gdbPath: arm-none-eabi-gdb`，`svdFile: R7FA8D1BH.svd`，`runToEntryPoint: hal_entry`，`preLaunchTask: flash`。
- `.vscode/tasks.json`：`flash` = `pyocd flash -t cortex_m --config pyocd.yaml -O connect_mode=pre-reset rtthread.elf`；`build` = `build.bat`。

## 构建（GCC，arm-none-eabi-gcc ≥13）
```
RTT_CC=gcc RTT_EXEC_PATH="$(dirname "$(command -v arm-none-eabi-gcc)")" scons
```
- rtconfig.py 默认 `EXEC_PATH=C:\Users\XXYYZZ` 是占位符，必须靠 `RTT_EXEC_PATH` 覆盖，否则报 "toolchain path not exist"。
- SConstruct 在缺 `rt-thread`/`libraries` 软链时回退到 `../../../rt-thread` 与 `../libraries`，**不跑 mklinks 也能编**（RTT_ROOT env 被 SConstruct 忽略，按 `os.path.exists` 重算）。
- rtconfig.py 的 gcc DEVICE 行 `-march=armv8.1-m.main+mve.fp+fp.dp` 配 `-mfpu=fpv5-sp-d16` 看似冲突，GCC 15.3 实测可过；产物含 `-O0 -g`（BUILD=debug）即带符号。

## 烧录
```
pyocd flash -t cortex_m --config pyocd.yaml -O connect_mode=pre-reset rtthread.elf
```
实测：擦 ~296KB / 写 ~267KB，RC=0。若芯片被锁（首次 SWD），`connect_mode=pre-reset` 已做预复位；仍失败再考虑整片擦。

## 仿真/调试验证（headless 自测脚本）
```
pyocd gdbserver -t cortex_m --config pyocd.yaml -O connect_mode=pre-reset > /tmp/srv.log 2>&1 &
sleep 6
arm-none-eabi-gdb -batch -ex "set pagination off" -ex "file rtthread.elf" \
  -ex "target remote 127.0.0.1:3333" \
  -ex "monitor halt" -ex "info registers" \
  -ex "info address hal_entry" -ex "x/4xw 0x02000000" -ex "bt" \
  -ex "monitor reset halt" -ex "thbreak hal_entry" -ex "continue" \
  -ex "info registers pc" -ex "bt 12"
```
**关键坑**：`target remote` 必须用 `127.0.0.1:3333`，不能写 `:3333`——后者在 Windows 上触发 error 138「系统试图将驱动器合并到合并驱动器上的目录」，连不上。
通过判据：monitor halt 成功；`info address hal_entry` 给出地址；`thbreak hal_entry` 显示 "Hardware assisted breakpoint ... file src\hal_entry.c, line 19"；`continue` 命中该行（源码级断点 + 单步可用）。

## VSCode 交互
F5 选 "Debug (pyOCD)"：preLaunchTask=flash 先编后烧 → 连 GDB → 跑到 hal_entry；可设断点/看寄存器/外设(SVD)/调用栈。"Attach (pyOCD)" 附着已烧录固件。要求 VSCode 终端 PATH 含 arm-none-eabi-gcc / scons / pyocd。

## 反模式
- 不要指望 OpenOCD 0.12（sysprogs）调试 RA8D1：scripts/target 里无 renesas/ra。
- 不要 `pyocd pack install` 拉 RA8D1：多数环境无 keil.com 网络。
- 不要连 `:3333`：用 `127.0.0.1:3333`。
- 不要以为需要 mklinks 软链才能编：SConstruct 回退即可。
