# ESP32 + Cortex-Debug 调试链路

适用组合：ESP32-S3（Arduino 或 ESP-IDF）+ VSCode Cortex-Debug（mcu-debug 全家桶）+ openocd-esp32（Espressif fork）+ xtensa-esp-elf-gdb。

> openocd-esp32 **不是** STM32 常用的 sysprogs openocd，两者不可混用。

## 1. 工具链路径布局

记 `<DATA>` = `arduino-cli config dump` 里的 data 目录，`<ESP32>` = `<DATA>/packages/esp32/tools`。版本号目录随 core 版本变化，**以实测 `ls <ESP32>` 为准**：

| 组件 | 相对路径 |
|---|---|
| openocd-esp32 | `<ESP32>/openocd-esp32/<ver>/bin/openocd.exe` |
| xtensa gdb | `<ESP32>/xtensa-esp-elf-gdb/<ver>/bin/xtensa-esp32-elf-gdb.exe` |
| binutils（nm/objdump） | `<ESP32>/esp-x32/<ver>/bin` —— **nm/objdump 在此，不在 gdb 目录** |
| openocd scripts | `<ESP32>/openocd-esp32/<ver>/share/openocd/scripts` |

Cortex-Debug 的 `armToolchainPath` 指向 **binutils 目录**（取 nm/objdump），`gdbPath` 指向 **gdb 目录**；两者不同，少了前者会报 `xtensa-esp-elf-nm.exe ENOENT`。

## 2. 调试接口（硬件）

- **内置 USB-Serial-JTAG**：VID `0x303a` / PID `0x1001`，走板载 USB 口（不是 USB-UART 桥的口）。用 `board/esp32s3-builtin.cfg`，免外接调试器。
- **USB-UART 桥（CH343 等）**：只能下载，**不能调试**。
- **外接 ESP-Prog**：用 `board/esp32s3-ftdi.cfg`。

## 3. JTAG 驱动安装（Windows，必需）

Windows 默认把 USB-Serial-JTAG 绑到串口驱动 `usbser`，libusb 无法原生打开 → openocd 报 `LIBUSB_ERROR_NOT_FOUND` / `LIBUSB_ERROR_ACCESS`。

官方解法（按标准描述符把 JTAG Interface 装 WinUSB，同时保留 CDC 串口）：

```
# 管理员 PowerShell
eim install-drivers
```

`eim` = Espressif Installation Manager。不要用旧 `idf-env driver install`，也不要 Zadig 手装——社区案例把 CDC 接口误装成 WinUSB 反而倒退（标准描述符里 JTAG 在 Interface 0）。

验证：

```bash
openocd -f board/esp32s3-builtin.cfg -c "init; reset halt; shutdown"
```

应看到 `esp_usb_jtag: Device found` + `Examination succeed` + 退出码 0。

## 4. 完整 launch.json

```jsonc
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "ESP32-S3 Debug (内置USB-Serial-JTAG)",
            "type": "cortex-debug",
            "request": "launch",
            "servertype": "openocd",
            "cwd": "${workspaceFolder}",
            "executable": "${workspaceFolder}\\.build\\<proj>.ino.elf",
            "toolchainPrefix": "xtensa-esp32-elf",
            "armToolchainPath": "<ESP32>\\esp-x32\\<ver>\\bin",
            "gdbPath": "<ESP32>\\xtensa-esp-elf-gdb\\<ver>\\bin\\xtensa-esp32-elf-gdb.exe",
            "serverpath": "<ESP32>\\openocd-esp32\\<ver>\\bin\\openocd.exe",
            "configFiles": ["board/esp32s3-builtin.cfg"],
            "searchDir": ["<ESP32>\\openocd-esp32\\<ver>\\share\\openocd\\scripts"],
            "overrideLaunchCommands": [],
            "runToEntryPoint": "app_init",
            "showDevDebugOutput": "none",
            "serverArgs": ["-d2"]
        },
        {
            "name": "ESP32-S3 Debug (内置USB-Serial-JTAG - 安全手动)",
            "type": "cortex-debug",
            "request": "launch",
            "servertype": "openocd",
            "cwd": "${workspaceFolder}",
            "executable": "${workspaceFolder}\\.build\\<proj>.ino.elf",
            "toolchainPrefix": "xtensa-esp32-elf",
            "armToolchainPath": "<ESP32>\\esp-x32\\<ver>\\bin",
            "gdbPath": "<ESP32>\\xtensa-esp-elf-gdb\\<ver>\\bin\\xtensa-esp32-elf-gdb.exe",
            "serverpath": "<ESP32>\\openocd-esp32\\<ver>\\bin\\openocd.exe",
            "configFiles": ["board/esp32s3-builtin.cfg"],
            "searchDir": ["<ESP32>\\openocd-esp32\\<ver>\\share\\openocd\\scripts"],
            "overrideLaunchCommands": [],
            "showDevDebugOutput": "none",
            "serverArgs": ["-d2"]
        },
        {
            "name": "ESP32-S3 Debug (ESP-Prog/FTDI)",
            "type": "cortex-debug",
            "request": "launch",
            "servertype": "openocd",
            "cwd": "${workspaceFolder}",
            "executable": "${workspaceFolder}\\.build\\<proj>.ino.elf",
            "toolchainPrefix": "xtensa-esp32-elf",
            "armToolchainPath": "<ESP32>\\esp-x32\\<ver>\\bin",
            "gdbPath": "<ESP32>\\xtensa-esp-elf-gdb\\<ver>\\bin\\xtensa-esp32-elf-gdb.exe",
            "serverpath": "<ESP32>\\openocd-esp32\\<ver>\\bin\\openocd.exe",
            "configFiles": ["board/esp32s3-ftdi.cfg"],
            "searchDir": ["<ESP32>\\openocd-esp32\\<ver>\\share\\openocd\\scripts"],
            "overrideLaunchCommands": [],
            "runToEntryPoint": "app_init",
            "showDevDebugOutput": "none",
            "serverArgs": ["-d2"]
        }
    ]
}
```

`<ESP32>` 是占位符（`<arduino-cli data>` + `packages/esp32/tools`）。复制进工程时**必须替换为绝对路径**（Cortex-Debug 不做变量展开）；不想在仓库暴露本机路径时，可改成 `${env:ESP32_TOOLS}` 并在系统环境变量中定义。

### 关键字段铁律

| 字段 | 取值 | 原因 |
|---|---|---|
| `overrideLaunchCommands` | `[]`（空数组，**必写**） | 覆盖 Cortex-Debug 默认的 `monitor reset halt`，否则必触发 `Arg list too long` 断连 |
| `serverArgs` | `["-d2"]`（**紧贴**，不要 `["-d","2"]`） | esp32 版 openocd 不认空格分隔，报 `Unexpected command line argument: 2` |
| `runToEntryPoint` | `"app_init"` 或 `"app_main"`，**不要 `"main"`** | Arduino elf 无 `main` 符号，`thb main` 失败 → continue 跑飞 → 断连 |
| `rtos` | **不写** | Arduino elf 无 FreeRTOS 符号，openocd 线程查询会拖垮 gdb 连接 |
| `armToolchainPath` | binutils（esp-x32）目录 | Cortex-Debug 拼 `toolchainPrefix-nm` 取符号 |

入口符号核对：`nm <elf> | grep -E "app_init|app_main"`。Arduino core 的 elf 通常同时存在 `app_init`(`_Z8app_initv`) 与 `app_main`(`_Z8app_mainv`)，任选其一。

## 5. 报错 → 根因 → 修复速查

| # | 报错 | 根因 | 修复 |
|---|---|---|---|
| 1 | `Unexpected command line argument: 2` | `serverArgs: ["-d","2"]` 空格分隔 | 改 `["-d2"]` |
| 2 | `xtensa-esp-elf-nm.exe ENOENT` | nm/objdump 在 binutils 目录，不在 gdb 目录 | `armToolchainPath` 指向 `esp-x32/<ver>/bin` |
| 3 | `LIBUSB_ERROR_NOT_FOUND` | Windows 串口驱动 usbser 绑死 USB-Serial-JTAG，libusb 打不开 | `eim install-drivers`（管理员） |
| 4 | `LIBUSB_ERROR_ACCESS` | 设备被独占——常是**残留 openocd/esptool 进程**占着 USB 复合设备 | `taskkill /F /IM openocd.exe` 后重试 |
| 5 | `Arg list too long` (from `monitor reset halt`) | 来自 Cortex-Debug 默认启动命令；attach 后重复复位触发协议崩 | 写 `"overrideLaunchCommands": []` |
| 6 | `Arg list too long` (from `flushregs`) | 新版 gdb 下 `flushregs` 是废弃别名，触发寄存器重读崩 | 删除该命令（空 override 即规避） |
| 7 | `Arg list too long` (from `reset init`) | `reset init` 停在 ROM 态、Flash MMU 未映射，后续 Flash 断点崩 | 用 `reset halt` 或空 override，不用 `reset init` |
| 8 | `Function "main" not defined` | Arduino elf 无 `main` 符号 | `runToEntryPoint` 改 `app_init`/`app_main` |
| 9 | `No hardware breakpoint support` | gdb 误判 xtensa 硬件断点数为 0 | 一般无需处理；空 override + 正确入口即可 |
| 10 | `Warn: No symbols for FreeRTOS!` | Arduino elf 不带 FreeRTOS 符号 | 删 `rtos: "FreeRTOS"` |
| 11 | `GDB server session ended` / `GDB Server Quit Unexpectedly` | `rtos` 导致 openocd 线程遍历失败断连（决定性真凶） | 删除 `rtos` 键 |
| 12 | `probe-rs-debug: Received unknown custom event` | 装了 probe-rs-debug 与 Cortex-Debug 抢 DAP 事件 | 卸载 probe-rs-debug 扩展 |
| 13 | `0x40000400 in ?? ()` + 服务端崩溃 | `reset init` 停在 ROM，早于 Flash 映射 | 同 #7 |
| 14 | openocd 启动即退出（无板子） | 板子没插在 USB-Serial-JTAG 口 | 插到板载 USB 口（非 USB-UART 桥口） |
| 15 | 调试正常但 RTOS 视图空 | 删 `rtos` 后没有任务线程列表 | 预期代价；需要线程视图须改用 ESP-IDF 工程导出 FreeRTOS 符号 |

## 6. 推荐排错顺序

1. **驱动**：先 `eim install-drivers`，再用命令行 openocd 的 `init; reset halt; shutdown` 验证 `Device found`。
2. **残留进程**：调试前 `tasklist | findstr openocd`，有则 `taskkill /F /IM openocd.exe`，否则 `LIBUSB_ERROR_ACCESS`。
3. **launch.json**：严格按铁律——`overrideLaunchCommands: []` + `serverArgs: ["-d2"]` + `runToEntryPoint: "app_init"` + **无 `rtos` 键**。
4. **扩展冲突**：确认未装 probe-rs-debug。
5. **看日志**：DEBUG CONSOLE 看不到服务端崩溃原因，必须看 **TERMINAL** 标签页的 gdb-server 输出。

## 7. 正常表现与代价

- 构建体积对比上一版看趋势，不记绝对值。
- 连接后 openocd 自动 halt（Flash 已映射），`runToEntryPoint` 停在入口，断点/单步/变量/调用栈正常。
- 代价：无 RTOS 线程视图（删 `rtos` 所致），对应用调试无影响。
