# west 构建、工具链探测与脚本陷阱

## 1. west 工作区

manifest（`west.yml`）拉齐 zephyr + hal + cmsis + fatfs + lvgl 等模块。典型布局：

```
west.yml                    # manifest
CMakeLists.txt              # 应用构建
prj.conf                    # Zephyr / LVGL / FatFs / 显示配置
boards/<board>.overlay      # 设备树覆盖
tools/openocd.cfg           # ST-Link SWD（adapter speed 等）
<app>/                      # 应用与 shell 命令
<bsp>/                      # 字库/字体/显示移植层
```

`west` 不在 PATH 时用模块方式调用：

```bash
python -m west build -b <board>/<soc> -d build -s .
```

- `ZEPHYR_BASE` 优先取环境变量（west 自动注入）；未设时回退工作区内的 `zephyr/`。
- MSYS2 下手动 `export ZEPHYR_BASE` 要用 **Windows 风格绝对路径**（`C:/...`），不要 POSIX
  风格（`/c/...`）。

## 2. CMakeLists：工具链自动探测（放在 find_package(Zephyr) 之前）

删掉 `build/` 后重编常报 `ZEPHYR_TOOLCHAIN_VARIANT not set ... Could not find Zephyr-sdk`
（致命）。在 `find_package(Zephyr)` 前自动探测，避免硬编码机器路径：

```cmake
if(NOT DEFINED ZEPHYR_TOOLCHAIN_VARIANT)
  set(ZEPHYR_TOOLCHAIN_VARIANT gnuarmemb)
endif()
if(NOT DEFINED GNUARMEMB_TOOLCHAIN_PATH)
  find_program(ARM_GCC arm-none-eabi-gcc)
  if(ARM_GCC)
    get_filename_component(_BIN "${ARM_GCC}" DIRECTORY)
    get_filename_component(GNUARMEMB_TOOLCHAIN_PATH "${_BIN}/.." ABSOLUTE)
  endif()
endif()
find_package(Zephyr REQUIRED HINTS <zephyr module path>)
```

## 3. 删掉 build/ 后必须支持全新构建

- `west build -t clean` 在 `build/` 不存在时会触发一次无 BOARD 的伪 configure（通常只被当
  WARN 吞掉）。一键脚本的 clean 步骤要写成"目录存在才执行"。
- `tasks.json` 的 build 任务**必须带 `-b <board>/<soc>`**：`python -m west build -b <board>/<soc>
  -d build -s .`；缺 `-b` 时删 build 后必失败。
- 顶层 `options.env` 注入 `ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb`。

## 4. 一键构建脚本（PowerShell / CI 友好）

- 去掉阻塞式 `pause`，收尾用 `exit /b %ERR%` 返回真实错误码（阻塞 pause 在 PowerShell 下会
  卡死或返回 255，掩盖真实结果）。
- 保持纯 ASCII / CRLF；`cd` 前先去掉 `%~dp0` 的尾随 `\`。
- 部分沙箱禁用 `cmd.exe`，`.bat` 端到端只能在用户本机验证；其内核命令就是已验证的 `west build`。

## 5. PowerShell 把 west 的 stderr 误报成红色错误

`west build` 的进度信息打到 stderr，PowerShell 会把它包装成 `RemoteException` /
`NativeCommandError`（红字），但 `BUILD_EXIT=0`、elf 正常生成。
**判定以退出码为准**，不要被红色输出误导。

## 6. 真机验收标志

- 心跳 LED 周期性翻转（系统存活）。
- 串口启动日志出现 Zephyr 版本行 + 字库自检行 + 主频自检行。
- halt 后 PC 落在屏刷新路径（如 `mipi_dbi_spi_write_helper`），说明持续渲染且无总线错误。
- 中文经 SD 字库实时取模渲染，ASCII 用移植点阵，字表未烧进 Flash。
