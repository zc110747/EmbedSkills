# 链接陷阱：--whole-archive 与弱符号

## 1. 现象

- 链接报错 `undefined reference to tud_descriptor_device_cb / configuration_cb / string_cb / tud_hid_descriptor_report_cb`：tinyusb 要求应用提供这些回调，但提供它们的 .c 目标文件被静态归档丢弃。
- 或运行期行为异常（如 HID 收不到主机报告）：tinyusb 的 `__weak` 回调桩静默胜出，实现覆盖的那个 .obj 因"未被直接引用"被归档丢弃。

## 2. 根因

ESP-IDF 把每个组件编译成静态库 `.a`。链接器只拉取"能解析当前未定义符号"的成员。自定义组件因为 `REQUIRES tinyusb`，在链接顺序上位于 tinyusb **之前**：其归档在 tinyusb 尚未产生 `tud_descriptor_*` 未定义引用前就被扫描，于是 `usb_descriptors.c.obj` 被丢弃。弱符号同理——强覆盖所在目标文件被丢弃，弱桩胜出。

## 3. 修复（结构性，不是打补丁）

ESP-IDF 组件天生是 `.a`；正解是**最终链接时用 `--whole-archive` 包裹自定义组件归档**，使其中每个目标文件无条件纳入。

推荐放在 `main/CMakeLists.txt`（从 main 引用组件目标，避免组件自链接报错）：

```cmake
idf_component_register(SRCS "app_main.c" INCLUDE_DIRS "." REQUIRES <comp_a> <comp_b>)

set(COMPONENTS_WHOLE <comp_a> <comp_b> <comp_c> <comp_d>)
foreach(comp ${COMPONENTS_WHOLE})
    idf_component_get_property(comp_lib ${comp} COMPONENT_LIB)
    if(comp_lib)
        target_link_libraries(${COMPONENT_TARGET} PRIVATE
            "-Wl,--whole-archive" "$<TARGET_FILE:${comp_lib}>" "-Wl,--no-whole-archive")
    endif()
endforeach()
```

要点：

- 从 `main` 引用组件目标（不是组件自引用），避开 CMake 自链接报错。
- `$<TARGET_FILE:...>` 在链接期解析为绝对路径，链接器直接打开 `.a`，无需 `-L`。
- ESP-IDF 已按 REQUIRES 把组件 `.a` 加入链接行；这里再包一层 whole-archive，同一归档去重无冲突，只是把所有成员纳入。

## 4. 不要做的事

- 不要用"在已拉取的目标文件里加 dummy 引用强制拉取另一目标文件"的打补丁方式——能 work 但丑且脆弱。
- 不要试图让 ESP-IDF 不生成 `.a`（组件模型固有）；whole-archive 是等价且受支持的做法。

## 5. 验证

构建后用工具链 nm 检查最终 elf：

```bash
xtensa-esp32s3-elf-nm -C build/<proj>.elf | grep -iE "tud_descriptor_device_cb|tud_hid_set_report_cb"
```

期望这些是 `T`（强定义、已链接），而非缺失或被 `W`（弱桩）取代。仍存在的 `W` 符号若是确实未实现、可接受用 tinyusb 默认桩的回调（如 `tud_suspend_cb` / `tud_resume_cb` / `tud_sof_cb`），不是问题。

## 6. 适配范围

上述机制不限于 tinyusb：任何"组件提供回调实现"或"组件提供强定义覆盖厂商 `__weak` 桩"的场景，都会因归档按引用挑选而失效，同样用 whole-archive 解决。

## 7. Git Bash 下的 ESP-IDF 环境陷阱

Windows + MSYS Git Bash 跑 ESP-IDF 有三个坑，构建/烧录脚本要一并解决：

1. `activate.ps1` 或裸 `idf.py` 在 Git Bash 下报 `Support for platform 'Windows-'` 或找不到 python。
2. Git Bash 注入 `MSYSTEM=MINGW64`，让 idf.py 走 MSYS 路径解析而告警/出错。
3. 缺 `PROCESSOR_ARCHITECTURE` / `ESP_IDF_VERSION` 等环境变量，需手动补。

环境脚本（工程根目录，手动激活；路径按本机安装位置替换）：

```bash
export IDF_TOOLS_PATH='<IDF_TOOLS_PATH>'
export IDF_PATH='<IDF_PATH>'
export ESP_ROM_ELF_DIR='<IDF_TOOLS_PATH>/esp-rom-elfs/<ver>/'
export IDF_PYTHON_ENV_PATH='<IDF_TOOLS_PATH>/python/<ver>/venv'
export IDF_CCACHE_ENABLE=1
export IDF_COMPONENT_STORAGE_URL="file://<IDF_TOOLS_PATH>"
export PATH="<venv>/Scripts:<toolchain>/bin:<cmake>/bin:<ninja>:<ccache>:$PATH"
PY="<venv>/Scripts/python.exe"
unset MSYSTEM
export PROCESSOR_ARCHITECTURE=AMD64
export ESP_IDF_VERSION=<ver>
```

用 `runpy` 剥掉 `MSYSTEM` 后再调用 idf.py，可绕开包装器直接进主流程：

```python
import os, sys, runpy
os.environ.pop('MSYSTEM', None)
tools_dir = os.path.join(os.environ['IDF_PATH'], 'tools')
sys.path.insert(0, tools_dir)
sys.argv = ['idf.py'] + sys.argv[1:]
runpy.run_path(os.path.join(tools_dir, 'idf.py'), run_name='__main__')
```

烧录脚本的端口选择范式：用 IDF 自带 python（含 pyserial）扫描 COM 口，**动态识别而非硬编码**；端口列表打印到 stderr（终端可见），选定端口作为 stdout 末行供 `tail -1` 解析；交互终端下可手动选，非交互下取默认或首个可用口。不传端口时用内置默认值，传入则直接采用。

`idf.py flash` 会自动构建缺失产物，已构建则直接烧录；三段（bootloader / partition-table / app）各自 `Hash of data verified`，最后 `Hard resetting via RTS pin... Done`。

**注意**：完整 clean 重建可能超过沙箱单命令超时，被 SIGTERM 打断在最终 app 链接；增量重建能正常完成。被打断后重跑一次构建即可（仅剩最终链接）。

**不要**走 `activate.ps1` 或裸 `idf.py`，也不要在 Git Bash 中额外套一层 cmd。
