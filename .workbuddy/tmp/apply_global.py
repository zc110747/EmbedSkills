# -*- coding: utf-8 -*-
"""把 description 收敛与 agent_created 补齐应用到**全局权威副本**。
铁律：全局是权威，改完再 sync 到镜像；反过来会被旧副本覆盖（2026-10-19 已踩过）。
"""
import os
import re

GLOBAL = os.path.expanduser("~/.workbuddy/skills")

NEW_DESC = {
"ra8d1-fsp-platform-notes":
 "Renesas RA8D1（R7FA8D1BH，Cortex-M85）FSP 平台经验：内存映射、GLCDC/MIPI DSI、xSPI/OSPI、SDRAM、pyOCD 烧录、SWD 取证。触发：RA8D1、R7FA8D1、FSP、GLCDC、r_ospi_b、OSPI、QSPI 读不到 ID。",
"pyocd-flm-inject-debug":
 "无 pyOCD 内建 target、pack target 在 DAP 上初始化失败时，用 pyocd_user.py 钩子注入 memory map+FLM，打通烧录与仿真。触发：pyOCD target 定制、FLM 注入、cortex-debug、pack init 失败。",
"lvgl9-mcu-porting":
 "LVGL v9 移植到裸机 MCU 的高频陷阱：v9 tick 回调、lv_color_hex 改 RGB888、静态库 vs section 表、启动画面/多屏交接、file(GLOB) 漏新文件。触发：LVGL 移植、v8 升 v9、首屏冻结、复位彩条、framebuffer 驱动。",
"replica-mock-harness":
 "复刻读写类工具的替身验收：用自研替身进程在没有目标程序时验证「读地址→指针链→写值→回读」接线，PASS/FAIL/SKIP 三分类把「环境缺位点」与「接线坏了」分开。触发：没有目标程序怎么验证、替身进程、验收脚本报 FAIL、SKIP 清单。",
"ra8d1-vscode-pyocd-debug":
 "VSCode 对 RA8D1（R7FA8D1BH）做源码级调试：pyOCD 无 target 时的绕过路径与 launch.json 配置。触发：RA8D1 调试、pyocd no matching devices、OpenOCD 无 renesas target、cortex-debug。",
"stm32-build-and-scaffold":
 "STM32 工程骨架与构建：CMake+Ninja 交叉编译、HAL 按需引入、Keil MDK 移植与 UV4 命令行、OpenOCD 烧录、Keil 产物接 Cortex-Debug。触发：新建 STM32 工程、未定义 HAL 符号、Keil HardFault/栈太小。",
"replica-memory-engine":
 "从外部读写目标进程内存的引擎方法论：符号解析、AOB 签名扫描（通配展开/越界钳制/全量校验）、多级指针链、位域读写、写后回读、代码洞与跳板 hook、x64 指令长度解码。触发：AOB 扫描命中不了、指针链走到一半变空、写了没生效。",
"piper-offline-tts":
 "Piper 本地离线 TTS 集成：CLI 契约（正文走 stdin、-f 出 WAV）、长文本实测能力、喂 TTS 前的文本准备（章节抽取/仅 UTF-8/非目标语言闸门）、模型哈希与许可核对、WAV 原子落地。触发：离线语音合成、piper、文本转 WAV、Markdown 转语音。",
"winforms-desktop-app":
 "C#/.NET WinForms 桌面应用：自绘圆角控件的 DPI 与裁剪、NAudio 3.x 播放器生命周期与无音频设备、外部 CLI 集成、同一 exe 兼作命令行、运行期条件跳过的测试。触发：WinForms 界面、NAudio 播放、自绘控件被裁、WFO1000、GUI 当 CLI。",
"replica-recon":
 "复刻第三方工具的第一步——逆向取证：确认原件身份与版本、PE/容器静态解析、资源与字符串挖掘、行为观察，并用「结论等级」标注证据强度。触发：复刻某工具先摸清做法、这文件什么编译器/框架、提取内嵌配置、静态结论能否当实现依据。",
"mcu-code-style-apply":
 "把 mcu-code-style 规范批量落到既有 STM32 工程：clang-format、GBK 编码保护、生成文件豁免、目录大小写改名、static 合并、MDK/GCC 双构验证与提交拆分。触发：给工程应用 code style、按新规范更新老项目。",
}

# 需要在 frontmatter 里补 agent_created: true 的篇目
ADD_AGENT_CREATED = ["lvgl9-mcu-porting", "mcu-code-style-apply", "ra8d1-vscode-pyocd-debug"]

fail = 0
for name, desc in NEW_DESC.items():
    p = os.path.join(GLOBAL, name, "SKILL.md")
    with open(p, encoding="utf-8", newline="") as f:
        txt = f.read()
    nl = "\r\n" if "\r\n" in txt else "\n"
    lines = txt.split(nl)
    hit = -1
    for i, ln in enumerate(lines):
        if ln.startswith("description:"):
            hit = i
            break
    if hit < 0:
        print("FAIL 无 description 行:", name)
        fail += 1
        continue
    old_len = len(lines[hit]) - len("description:")
    lines[hit] = "description: " + desc
    out = nl.join(lines)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    print("OK  %-30s %3d -> %3d" % (name, old_len, len(desc)))

for name in ADD_AGENT_CREATED:
    p = os.path.join(GLOBAL, name, "SKILL.md")
    with open(p, encoding="utf-8", newline="") as f:
        txt = f.read()
    if "agent_created:" in txt.split("\n---", 1)[0]:
        print("SKIP 已有 agent_created:", name)
        continue
    nl = "\r\n" if "\r\n" in txt else "\n"
    lines = txt.split(nl)
    for i, ln in enumerate(lines):
        if ln.strip() == "---" and i > 0:
            lines.insert(i, "agent_created: true")
            break
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(nl.join(lines))
    print("OK 补 agent_created:", name)

print("FAILED:", fail)
