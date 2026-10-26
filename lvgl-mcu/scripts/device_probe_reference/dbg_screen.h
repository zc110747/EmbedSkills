/*
 * dbg_screen.h -- TEMPORARY on-device screen forensics.
 *
 * Drop this file (and dbg_screen.c, and the one call in app_main.c) once the
 * layout has been confirmed on the real panel.  It exists because the RS485
 * rig is not wired up yet, so the only way to prove "the table really renders
 * 24 px CJK glyphs in the right cells" is to lift the frame out of the device.
 */
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

/** Spawn the one-shot dump task (waits ~3 s, then dumps, then dies). */
void dbg_screen_start(void);

#ifdef __cplusplus
}
#endif
