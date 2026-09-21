# 设备树 overlay 全量片段（Zephyr + STM32）

overlay 放 `boards/<board>.overlay`，west build 按 board 名自动选取。下面所有板级数值
（晶振频率、分频比、引脚、总线实例）都要按自己板子的原理图替换，这里只说明"怎么算"。

## 1. 时钟树：把 HSE 改成板载晶振

开发板默认常走 ST-Link 旁路时钟（如 8 MHz）；用户板若是无源晶振（如 25 MHz），**必须覆盖**，
否则所有派生时钟（含 SDMMC 源）全错：

```dts
&clk_hse { clock-frequency = <DT_FREQ_M(25)>; };   /* 同时去掉 hse-bypass */
&pll {
  div-m = <5>;    /* HSE / div-m = PLL 参考频率 */
  mul-n = <192>;  /* VCO = 参考频率 * mul-n，此处 VCO 960 MHz，SYSCLK 480 MHz */
};
```

**SDMMC 时钟源（PLL1Q）必须凑到 48 MHz**，否则 `f_mount` 返回 `FR_NOT_READY`：

```dts
&pll { div-q = <20>; };   /* 960 / 20 = 48 MHz */
```

算法：先定 VCO，再用 div-q 除到 48 MHz。改任一上游参数都要重算 div-q。

## 2. SPI + ST7789（MIPI-DBI）

```dts
&spi6 {
  status = "okay";
  st7789v: st7789v@0 {
    compatible = "sitronix,st7789v";
    spi-max-frequency = <DT_FREQ_M(40)>;
    reg = <0>;
    cmd-data-gpios = <&gpiog 15 GPIO_ACTIVE_HIGH>;   /* DC */
    /* width / height / rotation / vcom 按面板填；背光另配 gpio-leds 或 pwm */
  };
};
```

要点：

- Zephyr 的 MIPI-DBI 抽象把 DC 脚写成 `cmd-data-gpios`，不是裸机的"手动拉 DC"。
- 引脚（SCK/MOSI/CS/DC/BL）一律按原理图填，并确认与所选 SPI 外设的 AF 映射一致。
- dts 写对不等于会亮，屏还要靠 `display_blanking_off()` 显式点亮（见 `display-and-fonts.md`）。

## 3. SDMMC + FatFs 卷名

```dts
&sdmmc1 {
  bus-width = <4>;
  status = "okay";
  /* 需要 DMA 时加 idma 属性 */
};
```

Kconfig：

```
CONFIG_SDMMC_VOLUME_NAME="SD"
CONFIG_FF_STR_VOLUME_ID=1
```

Zephyr FatFs 用**字符串卷名**，盘符形如 `SD:`；同一块卡在裸机工程里通常是数字盘符 `1:`，
移植时不要照抄。

## 4. USART 调试串口 + shell

```dts
&usart1 { status = "okay"; current-speed = <115200>; };

/ {
  chosen { zephyr,shell-uart = &usart1; };
};
```

`zephyr,shell-uart` 是 Zephyr shell 拿到串口的唯一入口；改波特率要同步 dts 与 shell 侧配置。
