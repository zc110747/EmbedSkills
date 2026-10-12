---
name: avr-flash-ram
description: AVR(avr-gcc/avr-libc)RAM溢出诊断修复:字符串字面量默认进.data挤爆栈,致固件空载正常、收命令即复位。含avr-size/nm/objdump定位、PSTR/PROGMEM正解、%S与%s区别。触发:AVR复位、.data异常大、avr-size。
agent_created: true
---
# AVR Flash vs RAM: the silent .data overflow

## When to use this skill
- Building bare-metal AVR firmware (no Arduino framework) with avr-gcc/avr-libc.
- Symptom: firmware boots once cleanly (idle UART prints fine) but **resets/garbles
  when you send it commands** — repeated boot banners, corrupted angles (`STATUS S6=0(H)`),
  `ERR UNKNOWN ...`.
- `avr-size` shows `.data` much larger than your few global variables (e.g. `.data`=1610
  but you only have a couple of small structs).

## Root cause (the classic AVR gotcha)
avr-gcc **copies every string literal (`"..."`) into `.data` (RAM)** at startup, unless you
explicitly put it in flash. On a 2 KB part (ATmega328P) this fills RAM:
- `.data` + `.bss` grows to ~1942/2048, leaving **~97 B of stack**.
- Any function with a stack buffer (e.g. `uart_printf` using a 160 B local) overflows the
  stack into `.bss` during command handling → crash/reset.

## Diagnose (fast, no hardware needed)
```bash
avr-size -A firmware.elf | grep -E "\.text|\.data|\.bss"
# RAM = .data + .bss ; stack headroom = 2048 - (256 + .data + .bss)
avr-nm -S --size-sort -t d firmware.elf | grep -iE ' [dD] '   # named .data symbols
avr-objdump -s -j .data firmware.elf | grep -iE "本项目|commands|STATUS"  # strings in RAM!
```
If you see your help/status text inside `.data`, that's the smoking gun.

## Fix (the canonical pattern)
1. **Print from flash.** Make `uart_puts`/`uart_printf` read flash:
   ```c
   #include <avr/pgmspace.h>
   void uart_puts(PGM_P s) {            // s points into flash
       char c;
       while ((c = (char)pgm_read_byte(s++)) != '\0') uart_putc(c);
   }
   int uart_printf(PGM_P fmt, ...) {    // fmt in flash
       char buf[96];                   // keep small; stack is precious
       va_list ap; va_start(ap, fmt);
       int n = vsnprintf_P(buf, sizeof buf, fmt, ap);  // _P reads flash fmt
       va_end(ap);
       if (n > 0) uart_puts_ram(buf);  // buf itself is RAM; use a ram-put for it
       return n;
   }
   ```
   Call sites: `uart_puts(PSTR("hello")); uart_printf(PSTR("v=%u\r\n"), v);`
2. **Const tables → PROGMEM + `pgm_read_*`:**
   ```c
   static const uint8_t TAB[4] PROGMEM = {9,8,6,7};
   uint8_t id = pgm_read_byte(&TAB[i]);
   ```
3. **Inline flash strings inside PROGMEM structs** — `PSTR()` is NOT a constant
   initializer, so it can't be used inside a `static const` aggregate. Store the
   string as an inline `char name[12]` field; the whole struct is PROGMEM, so the
   bytes live in flash. Print via `uart_puts((PGM_P)&TAB[i].name[0])`.
4. **`_P` printf format notes:** `%s` reads a **RAM** string, `%S` (uppercase) reads a
   **flash** string. When passing a flash string as a `%s` arg, either copy to a RAM
   buffer first or use `%S` — or just `uart_puts()` it separately.

## Verify
Rebuild (expect `.data` to drop by ~1 KB, RAM ≈ 400–500 B, stack headroom ≈ 1300+ B),
flash, and run an automated command burst. Stable under load = fixed.

## Hard rule to carry forward
On AVR, **every `uart_puts`/`printf` literal must be `PSTR()`**, every const table must be
`PROGMEM`. Reintroducing a plain `"..."` silently re-bloats `.data` and re-breaks the stack.
