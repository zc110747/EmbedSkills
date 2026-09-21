# OpenOCD 烧录、双镜像 Bootloader 与工程文档/UI 约定

## 一、OpenOCD 烧录配置（放工程根）

`<工程>.cfg`（烧写本板）：

```tcl
source [find interface/stlink.cfg]
transport select swd
source [find target/stm32h7x.cfg]
```

烧录命令：

```bash
openocd -f <工程>.cfg -c "program build/debug/<target>.elf verify reset exit"
```

- OpenOCD 0.12 用 `transport select swd`（**不支持旧 `hla_swd`**）。
- 缺 cfg 的工程按芯片补建：H7 用 `stm32h7x.cfg`，F4 用 `stm32f4x.cfg`。
- 用本板作探针访问另一块目标板（例如自研 CMSIS-DAP v1 探针，见 `mcu-debug-forensics`）时，
  另写一份 `cmsis_dap` interface 的 cfg，同样放工程根，并在 `launch.json` 多配一条 `attach` 配置。
- 报错判读：找不到 `[find ...]` 脚本或路径错误属**配置错误**，需修正；
  仅 “no probe attached” 一类 adapter 报错属**正常**（需真机在场）。

## 二、双固件镜像 Bootloader 工程约定

Bootloader + App 共存于同一片内部 Flash，需**两套独立构建 + 固定地址分区**。

内存布局示例（H743 2MB 双 Bank，按实际芯片改）：

| 区域 | 地址 | 说明 |
|------|------|------|
| Bootloader | `0x08000000` sec0 (128KB) | 主构建 `*_boot.elf` |
| App 镜像 | `0x08020000` sec1-14 | 独立 CMake + 独立 `.ld`（`ORIGIN=0x08020000`） |
| 版本槽 | `0x08021000`（App 偏移 0x1000，4B） | `.app_version` 固定段 |
| 配置区 | `0x081E0000` sec15 (64B) | magic / len / version / hmac / crc32 |

约定：

- **两套独立 CMake + 链接脚本**：bootloader 与 app 各一个工程目录，app 的 `.ld` `ORIGIN`
  必须指向 App 基址，两份链接脚本互相独立；改 `.ld` 后务必让 CMake 跟踪（`LINK_DEPENDS`）。
- **升级包可经 U 盘注入**：QSPI + FatFs + TinyUSB MSC 把 QSPI 暴露为 PC U 盘；
  升级包元数据（名称 / 长度 / 校验 / 版本）与同名 `.bin` 落到根目录 → 复位后 Bootloader
  校验 → 擦写 → 跳 App。
- **跳转前清环境**与**擦写引擎放 AXI SRAM（绝不放 DTCM）**，
  详见 `stm32-peripherals-and-memory/references/h7-flash-bootloader.md`。
- **防砖**：任何校验失败在擦写前 abort，已运行 App 不被破坏。
- 验收方法（gdb 直调编程函数与 Flash 回读）见 `embedded-verification-acceptance`。

## 三、LVGL 多页面 UI 拆分约定

页面超过 2~3 页时拆成：`app/app_ui.c` 框架 + `app/ui/page_*.c` 每页独立，
共享声明集中在 `ui_common.h`；`CMakeLists.txt` 必须把 `app/ui/*.c` 纳入源集并重跑 `cmake`。

注意点：
- 页面文件里的 `static` 符号与 `ui_common.h` 的 `extern` 声明不得重名冲突。
- 切页时先解绑回调再删除对象，避免野指针。
- 多个页面共用同一份 UI 主题/字体时，只保留一份定义，其余 `extern` 引用。

## 四、工程 README 约定

README 固定 8 章，随代码同步更新：概述 / 硬件接口 / 工程结构 / 开发流程 / 构建运行 /
调试烧录 / 验收自测 / 常见问题。

- 资源占比（Flash / RAM）、编译警告数一律以**数字**显式给出，不写「基本无警告」这类模糊描述。
- 分区表、引脚表、时钟频率等以表格给出，便于与本 skill 的构建配置互相对照。
