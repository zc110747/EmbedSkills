---
name: pyocd-flm-inject-debug
description: 无 pyOCD 内建 target、pack target 在 DAP 上初始化失败时，用 pyocd_user.py 钩子注入 memory map+FLM，打通烧录与仿真。触发：pyOCD target 定制、FLM 注入、cortex-debug、pack init 失败。
agent_created: true
---

# pyOCD FLM 注入 + VSCode 在线仿真

## 1. 何时用这条链路

判据（满足其一即走本方案）：

- `pyocd list --targets` 无该芯片，或 pack target 连接报 init/DAP 错（常见于板载 CMSIS-DAP 探针）
- OpenOCD 能连（识别核、能 halt/resume）但**没有 flash bank** → 只能调试不能烧录
- 芯片是 TrustZone 架构（code flash 不在 0x0，如 0x02xxxxxx），通用 target 的默认 memory map 全部对不上

结论形态：**generic `cortex_m` target + 官方 DFP FLM 算法注入**，而不是修 pack target。

## 2. 关键机制（决定成败，别靠猜）

- ⚠️ **pyOCD 配置文件没有顶层 `targets:` 自定义 target 机制**：`pyocd.yaml` 的顶层键全部按 session option
  处理（只有 `probes`/`logging` 等特殊键）。自定义 memory map 只能走 user script。
- ✅ user script `pyocd_user.py`（工程根自动发现）提供 delegate 钩子。`will_init_target(target, init_sequence)`
  在 init 序列执行**前**被调用；在里面替换 `target.memory_map` 后，init 序列的 **`create_flash` task**
  会对每个 FLASH region 自动跑 `FlmFlashRegionBuilder.finalise_region()` → 加载 FLM、建 Flash 实例、绑回 region。
  即：**只需注入带 `flm=` 的 FlashRegion，不要自己 `finalise_region` + 手工 new Flash**（那是独立脚本 API 才需要的）。
- FLASH region 的 algo RAM 用私有字段：`region._RAMstart` / `region._RAMsize`（值取自 DFP 的 RAMstart/RAMsize）。

## 3. 落地三件套（工程根，全部相对路径）

### `pyocd.yaml`

```yaml
target_override: cortex_m   # generic target，不用 pack target
frequency: 1000000          # SWD 时钟；不稳就降到 100k
```

### `pyocd_user.py`

```python
import os
from pyocd.core.memory_map import FlashRegion, MemoryMap, RamRegion

FLM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools", "flash", "<chip>.FLM")

def _build_memory_map():
    flash_region = FlashRegion(start=0x02000000, length=0x1F8000, flm=FLM_PATH, name="code_flash")
    flash_region._RAMstart = 0x22000000   # DFP RAMstart/RAMsize
    flash_region._RAMsize  = 0x7800
    return MemoryMap([flash_region, RamRegion(start=0x22000000, length=0xE0000, name="sram")])

def will_init_target(target, init_sequence):
    target.memory_map = _build_memory_map()
```

FLM 从官方 DFP pack 取：`python -c "import zipfile;zipfile.ZipFile('<x>.pack').extract('**/<chip>.FLM')"`
（pack 也常被 CMSIS 工具修补后才可用；SVD 同理在 `SVD/` 下，供 VSCode 外设寄存器视图）。

⚠️ **memory map 必须覆盖 ELF 里「带内容」的全部 `PT_LOAD` 段**，否则 gdb `load` 整段中止
（`pyocd flash` 只是警告跳过，所以「命令行能烧 ≠ F5 能跑」）。先枚举：
`arm-none-eabi-readelf -l <elf> | grep LOAD` — 凡 FileSiz≠0 的段都要有对应 region。
典型漏项是**选项字节 / 配置区**（RA8D1 实测）：
- `0x0300A100` 选项字节 → `RA8D1_CCONF.FLM`
- `0x27030080` data-flash 选项区 → **`RA8D1_DCONF.FLM`**（DevAdr `0x27030050`、szDev `0x3B0`）
  ⚠️ 这条**在 DFP 的 pdsc 里根本查不到**；只能解析 FLM 内 `FlashDevice` 结构体拿真值：
  offset 132 = DevAdr(4B)、136 = szDev(4B)。**不确定某 FLM 管哪段地址时就去解析它，别猜。**
另外 `pyocd_user.py` 由 pyOCD 从 **`project_dir`（当前工作目录）** 自动发现
（默认名 `pyocd_user.py` / `.pyocd_user.py`），所以 flash 任务/调试会话的 cwd 必须落在工程根。

### `.vscode/launch.json`（servertype pyocd）

```json
{"name":"Debug (pyOCD)","type":"cortex-debug","request":"launch","servertype":"pyocd",
 "cwd":"${workspaceFolder}","executable":"${workspaceFolder}/build/firmware.elf",
 "targetId":"cortex_m",
 "serverArgs":["--config","pyocd.yaml","-O","connect_mode=pre-reset"],
 "gdbPath":"arm-none-eabi-gdb","runToEntryPoint":"<entry>",
 "preLaunchTask":"build","svdFile":"${workspaceFolder}/<chip>.svd"}
```

> ⚠️ 传给 pyOCD 的目标属性名是 **`targetId`**（cortex-debug 内部 `serverArguments()` 里
> `s.push("--target", …)`），**不是** `targetOverwrite` / `targetOverride`。
> 写错**不报错、只是静默不生效**（回退到默认 target），排起来很费时间。
> 核实方法：`grep -rhoE "serverArguments\(\)\{.{0,500}" ~/.vscode/extensions/marus25.cortex-debug-*/dist/*.js`

`tasks.json` 只留 `configure/build/clean/flash` 四任务，工具一律裸程序名（PATH）：
flash = `pyocd flash -t cortex_m -O connect_mode=pre-reset build/firmware.elf`（`dependsOn: build`）。

## 4. 验证顺序（每步都要有判据，别跳）

1. `pyocd list` → 探针可见（缺探针属环境缺失，不算配置 FAIL）
2. `pyocd commander -t cortex_m -O connect_mode=halt -c "reg pc" -c "quit"` → 读出 PC
3. `pyocd flash ... build/firmware.elf` → 判据：`Erased N bytes (x sector), programmed N bytes` 且 exit 0
4. `pyocd gdbserver -t cortex_m` + `arm-none-eabi-gdb -batch -ex "target extended-remote localhost:3333" ...`
   → 判据：断点命中并打印 `file <src>.c, line N`
5. VSCode F5 → 停在入口函数行

## 5. 坑清单（都是实测踩出来的）

- ⚠️ **`runToEntryPoint` 填真实入口**：裸机工程常是 `entry()`/`hal_entry()` 而非 `main()`，
  填错会 `Function "main" not defined`（或 gdb 卡在 continue）。先 `nm elf | grep -E " [Tt] "`。
- ⚠️ **只有 Debug 构建带 `-g`**：Release elf 无 `.debug_info` → 源码级断点和变量全失效。
  交付前 `readelf -S elf | grep debug_info` 确认；最终产物留 Debug 版。
- ⚠️ **软件断点插不进 flash**：OpenOCD 无 flash bank 时报 `Cannot insert breakpoint / Cannot access memory`。
  OpenOCD 侧加 `gdb_breakpoint_override hard`（走 FPB 硬件断点）；pyOCD 侧由 FLM/memory map 保证可写。
- ⚠️ **不要在 openocd.cfg 里写 `configure -event gdb-attach { reset halt }`**：与 gdb attach 握手竞争，
  结果 `continue` 永不 resume。复位交给调试器（`monitor reset halt` / cortex-debug overrideLaunchCommands）。
- ⚠️ **运行中 app 的 D-cache 会破坏 algo RAM 加载**（M7/M85）：烧录用 `connect_mode=pre-reset`
  （等价"先复位再编程"）；attach 调试不要 pre-reset。
- ⚠️ gdb 打印地址会省略前导 0（`0x02000110` 显示成 `0x2000110`），不是地址错，别误判。
- `Failed to add data chunk: no memory region defined for address 0x...`：elf 含 option-setting / 外设映射
  section 而未定义 region。若独立烧录脚本行为一致且程序能跑，属**已知可忽略**，写进 README 不要当成 bug 修。
- 芯片有超大 `.bin`（几百 MB）通常是 linker 把段放到了 SDRAM/QSPI 高地址 → 烧录用 `.elf`/`.hex`，不用 `.bin`。

### IDE（cortex-debug F5）路径专属坑：`pyocd flash` 能过 ≠ gdb `load` 能过

- ❌ `spawn pyocd ENOENT`：pyocd 装在 venv 里时，VSCode 继承的 PATH 没有它（终端能跑不代表 spawn 能找到）。
  修法：装到**系统 Python**（其 `Scripts/` 通常在 PATH），保持配置里只写裸程序名。
- ❌ gdb `load` **整段中止**（`pyocd flash` 只是警告跳过同一批段）：任何不可写 section 都会让 load 失败，
  典型是 option-setting / data-flash 配置段。修法按优先级：
  0. **在 memory map 里给这些段配好 region + FLM**（首选：不动工程源码，且这些配置区本来就在烧录范围内）——见 §3
  1. linker 给这些输出段加 **`(NOLOAD)`**（FileSiz=0，load 跳过）——零警告，但语义变成「配置区不再被烧」
  2. objcopy `--remove-section` 另存调试 elf——可行但会刷 `empty loadable segment detected` 警告
  3. ⚠️ **`/DISCARD/` 常无效**：输入 section 被 `KEEP()` 引用时 ld 不丢
- ⚠️ **没插探针时 `pyocd flash` 会无输出挂起**（不是干净报错，会一直等）：
  下命令前先 `pyocd list` 确认探针在；挂住了就 `taskkill /F /IM pyocd.exe`。
- ❌ `flash erase sector timed out` / `Error finishing flash operation`：pyocd flash 算法默认超时仅 10s，
  gdb 的 RSP flash 路径更慢 → 配置 `flash.timeout.init/erase_sector/program`（30/60/60）。
- ⚠️ load 重写 flash 后**不复位就 continue 会跑飞**（SIGSEGV / Default_Handler）：
  `preLaunchCommands: ["monitor reset halt"]`；`runToEntryPoint` 内部是「临时断点 + 复位 + continue」，等价。
- ❌ `Failed to launch PyOCD GDB Server: Timeout.`：cortex-debug 靠正则匹配 server 输出判断就绪，
  内置 `/GDB server started (at|on) port/`，而 **pyocd ≥0.34 输出 `GDB server listening on port`**
  → 永不匹配。修法：`"overrideGDBServerStartedRegex": "GDB server (started|listening) (at|on) port"`。
  （pyocd 日志全走 stderr，stdout 为 0 字节；cortex-debug 的 `onStderr` 也做匹配，所以不是流的问题。）
  排查：`grep -rhoE "initMatch=.{0,140}" ~/.vscode/extensions/marus25.cortex-debug-*/dist/*.js` 挖内置正则。
- ⚠️ 改 linker script 后 Ninja **不会自动重链**（`-T script.ld` 没进依赖图）→ 必须 `rm build/firmware.elf` 再 build。

## 6. 验收判据（写进 README 的数字）

双构零警告 + FLASH/RAM 占比百分比 + 烧录速率与扇区数 + 断点命中处的 `pc` 与源码行 + 核型号识别行
（如 `Cortex-M85 r0p2`）+ 断点/观察点数量。
