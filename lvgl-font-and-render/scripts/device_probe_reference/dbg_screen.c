/*
 * dbg_screen.c -- TEMPORARY on-device screen forensics (see dbg_screen.h).
 *
 * Three independent probes, all printed to the USB serial console:
 *
 *   TEXTFIT  for every label: natural text size vs the box we gave it
 *            -> proves nothing is clipped horizontally / vertically
 *   GLYPH    for every CJK codepoint the UI uses: glyph descriptor, ink
 *            coverage (a missing/empty glyph shows up as 0 %), plus an
 *            ASCII-art render of the character's real bitmap
 *   SNAP     a real frame lifted out of the panel with lv_snapshot
 *
 * SNAP encoding -- palette indices, 1 hex char per pixel:
 *
 *     ===SNAP begin w=800 h=480 step=1 cols=800 rows=480 pal=15===
 *     P00=E8F1FA                     ... up to 15 most frequent colours
 *     R000:001122...|<checksum>      one line per emitted row
 *     ===SNAP end===
 *
 * The first version emitted 6 hex chars per pixel (RRGGBB).  At step 2 that
 * is ~580 KB per frame, which the USB console cannot drain inside a sane
 * capture window -- the frame arrived truncated.  Histogramming the frame to
 * 15 palette colours and shipping one character per pixel cuts the payload
 * 6x for identical visual information, because this UI is drawn from a
 * handful of flat colours.
 *
 * Three frames are emitted, one per display state the table can be in:
 *   0  step 1 (crisp 1:1)  row A = all three checks pass; row B = zero read
 *                          FAILED -> exercises blank / "-" / value / 通过
 *   1  step 2              row B = worst case, 7-char values, all 未通过
 *   2  step 2              both rows after 重置 -> everything blank
 */
#include "dbg_screen.h"

#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_heap_caps.h"
#include "esp_log.h"

#include "lvgl.h"
#include "extra/others/snapshot/lv_snapshot.h"

#include "lvgl_port.h"
#include "ui_weigh.h"
#include "weigh_model.h"

LV_FONT_DECLARE(font_zh_24);

static const char *TAG = "dbg";

/* --------------- every CJK string the UI can put on screen -------------- */
static const char *SAMPLES[] = {
    "通道", "零点读取cnts", "挂钩零点cnts", "4000g读取cnts", "500g读取cnts",
    "20kg计算cnts", "500g计算质量g", "零点测试", "额定输出", "线性度", "测试结果",
    "零点", "挂钩", "4000g", "500g", "重置",
    "通过", "未通过", "-", "A", "B",
    "准备", "读取中", "读取完成", "读取超时", "已清除",
};
#define SAMPLE_NUM ((int)(sizeof(SAMPLES) / sizeof(SAMPLES[0])))

#define ART_MAX      48      /* ASCII-art the first N distinct glyphs */

/* ------------------------------------------------------------------ utf8 */
static uint32_t utf8_next(const char **pp)
{
    const unsigned char *s = (const unsigned char *)*pp;
    uint32_t cp;

    if (s[0] < 0x80) {
        cp = s[0];
        *pp += 1;
    } else if ((s[0] & 0xE0u) == 0xC0u) {
        cp = ((uint32_t)(s[0] & 0x1Fu) << 6) | (uint32_t)(s[1] & 0x3Fu);
        *pp += 2;
    } else if ((s[0] & 0xF0u) == 0xE0u) {
        cp = ((uint32_t)(s[0] & 0x0Fu) << 12) | ((uint32_t)(s[1] & 0x3Fu) << 6) |
             (uint32_t)(s[2] & 0x3Fu);
        *pp += 3;
    } else if ((s[0] & 0xF8u) == 0xF0u) {
        cp = ((uint32_t)(s[0] & 0x07u) << 18) | ((uint32_t)(s[1] & 0x3Fu) << 12) |
             ((uint32_t)(s[2] & 0x3Fu) << 6) | (uint32_t)(s[3] & 0x3Fu);
        *pp += 4;
    } else {
        cp = '?';
        *pp += 1;
    }
    return cp;
}

static void escape(const char *src, char *dst, size_t n)
{
    size_t j = 0;

    for (; *src != '\0' && j + 2 < n; src++) {
        dst[j++] = (*src == '\n') ? '|' : *src;
    }
    dst[j] = '\0';
}

/* ------------------------------------------------- 1. label fit check --- */
static void probe_text_fit(void)
{
    lv_obj_t *scr = lv_scr_act();
    const uint32_t n = lv_obj_get_child_cnt(scr);
    uint32_t checked = 0, over = 0;

    lv_obj_update_layout(scr);

    printf("===TEXTFIT begin children=%u===\n", (unsigned)n);
    for (uint32_t i = 0; i < n; i++) {
        lv_obj_t *o = lv_obj_get_child(scr, i);
        if (!lv_obj_check_type(o, &lv_label_class)) {
            continue;
        }

        const char *t = lv_label_get_text(o);
        if (t == NULL || t[0] == '\0') {
            continue;   /* blank cell: nothing can overflow */
        }

        /* natural, un-wrapped text extent in the real 24 px font */
        lv_point_t sz;
        lv_txt_get_size(&sz, t, &font_zh_24, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);

        const int bw = (int)lv_obj_get_width(o);
        const int bh = (int)lv_obj_get_height(o);
        const int dx = (int)sz.x - bw;
        const int dy = (int)sz.y - bh;

        char esc[96];
        escape(t, esc, sizeof(esc));

        checked++;
        if (dx > 0 || dy > 0) {
            over++;
        }
        printf("LABEL[%02u] nat=%dx%d box=%dx%d dx=%+d dy=%+d %-8s \"%s\"\n",
               (unsigned)i, (int)sz.x, (int)sz.y, bw, bh, dx, dy,
               (dx > 0 || dy > 0) ? "OVERFLOW" : "fit", esc);
    }
    printf("===TEXTFIT end checked=%u overflow=%u===\n",
           (unsigned)checked, (unsigned)over);
}

/* ------------------------------------------------- 2. glyph ink check --- */
static int glyph_pixel(const uint8_t *bm, int stride, int bpp, int x, int y)
{
    if (bm == NULL) {
        return 0;
    }
    const uint8_t *row = bm + (size_t)y * (size_t)stride;

    switch (bpp) {
    case 1:
        return (row[x >> 3] >> (7 - (x & 7))) & 1;
    case 2:
        return (row[x >> 2] >> (6 - 2 * (x & 3))) & 3;
    case 4:
        return (row[x >> 1] >> (4 - 4 * (x & 1))) & 0x0F;
    default:
        return row[x];
    }
}

static void glyph_report(uint32_t cp, bool art)
{
    lv_font_glyph_dsc_t g;
    memset(&g, 0, sizeof(g));

    if (!lv_font_get_glyph_dsc(&font_zh_24, &g, cp, 0)) {
        printf("GLYPH U+%04X *** MISSING ***\n", (unsigned)cp);
        return;
    }

    const uint8_t *bm = lv_font_get_glyph_bitmap(&font_zh_24, cp);
    const int stride = (g.box_w * g.bpp + 7) / 8;
    const int total = (int)g.box_w * (int)g.box_h;
    int ink = 0;

    for (int y = 0; y < g.box_h; y++) {
        for (int x = 0; x < g.box_w; x++) {
            if (glyph_pixel(bm, stride, g.bpp, x, y) != 0) {
                ink++;
            }
        }
    }

    printf("GLYPH U+%04X box=%dx%d adv=%d bpp=%d ink=%d/%d %d%%\n",
           (unsigned)cp, (int)g.box_w, (int)g.box_h, (int)g.adv_w,
           (int)g.bpp, ink, total, total ? (100 * ink / total) : 0);

    if (!art || bm == NULL) {
        return;
    }
    for (int y = 0; y < g.box_h; y++) {
        char l[8 + 64];
        int p = snprintf(l, sizeof(l) - 1, "  |");
        for (int x = 0; x < g.box_w && p < (int)sizeof(l) - 2; x++) {
            const int v = glyph_pixel(bm, stride, g.bpp, x, y);
            l[p++] = (v >= 10) ? '#' : ((v >= 4) ? '+' : ((v > 0) ? '.' : ' '));
        }
        l[p++] = '|';
        l[p] = '\0';
        printf("%s\n", l);
    }
}

static void probe_glyphs(void)
{
    uint32_t list[64];
    int n = 0;

    printf("===GLYPH begin===\n");
    for (int i = 0; i < SAMPLE_NUM; i++) {
        const char *p = SAMPLES[i];
        while (*p != '\0') {
            const uint32_t cp = utf8_next(&p);
            if (cp < 0x80) {
                continue;
            }
            bool seen = false;
            for (int k = 0; k < n; k++) {
                if (list[k] == cp) {
                    seen = true;
                    break;
                }
            }
            if (!seen && n < (int)(sizeof(list) / sizeof(list[0]))) {
                list[n++] = cp;
            }
        }
    }

    printf("distinct CJK glyphs used by the UI: %d\n", n);
    for (int i = 0; i < n; i++) {
        glyph_report(list[i], i < ART_MAX);
    }
    printf("===GLYPH end n=%d===\n", n);
}

/* ------------------------------------------------- 3. frame extraction -- */
/* RGB444 quantisation: the UI is drawn from a handful of flat colours, so
 * 4096 buckets already hold every real colour exactly, and the palette
 * search below then collapses the antialiased blends onto their nearest
 * neighbour.  */
#define QMAX        4096
#define PAL_MAX     15

static uint16_t s_hist[QMAX];
static uint8_t  s_lut[QMAX];

static inline uint16_t q444(uint32_t r, uint32_t g, uint32_t b)
{
    return (uint16_t)(((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4));
}

static inline uint32_t un444(uint16_t q)
{
    const uint32_t r = (uint32_t)((q >> 8) & 0x0Fu) * 17u;
    const uint32_t g = (uint32_t)((q >> 4) & 0x0Fu) * 17u;
    const uint32_t b = (uint32_t)(q & 0x0Fu) * 17u;
    return (r << 16) | (g << 8) | b;
}

static void snap_emit(int step)
{
    const uint32_t need =
        lv_snapshot_buf_size_needed(lv_scr_act(), LV_IMG_CF_TRUE_COLOR);
    lv_color_t *buf = (lv_color_t *)heap_caps_malloc(need, MALLOC_CAP_SPIRAM);

    if (buf == NULL) {
        printf("===SNAP FAIL alloc %u bytes===\n", (unsigned)need);
        return;
    }

    lv_img_dsc_t dsc;
    if (lv_snapshot_take_to_buf(lv_scr_act(), LV_IMG_CF_TRUE_COLOR, &dsc, buf,
                                need) != LV_RES_OK) {
        printf("===SNAP FAIL take_to_buf===\n");
        heap_caps_free(buf);
        return;
    }

    const int W = (int)dsc.header.w;
    const int H = (int)dsc.header.h;
    const int CW = W / step, CH = H / step;
    const int NPX = CW * CH;

    uint16_t *q = (uint16_t *)heap_caps_malloc((size_t)NPX * sizeof(uint16_t),
                                               MALLOC_CAP_SPIRAM);
    if (q == NULL) {
        printf("===SNAP FAIL q alloc %d px===\n", NPX);
        heap_caps_free(buf);
        return;
    }

    /* ---- pass 1: box-average every block, histogram the quantised colour */
    memset(s_hist, 0, sizeof(s_hist));
    for (int by = 0; by < CH; by++) {
        for (int bx = 0; bx < CW; bx++) {
            uint32_t r = 0, g = 0, b = 0;

            for (int dy = 0; dy < step; dy++) {
                const lv_color_t *row =
                    buf + (size_t)(by * step + dy) * (size_t)W + bx * step;
                for (int dx = 0; dx < step; dx++) {
                    r += (uint32_t)row[dx].ch.red * 255u / 31u;
                    g += (uint32_t)row[dx].ch.green * 255u / 63u;
                    b += (uint32_t)row[dx].ch.blue * 255u / 31u;
                }
            }

            const uint32_t k = (uint32_t)(step * step);
            const uint16_t qq = q444(r / k, g / k, b / k);
            q[by * CW + bx] = qq;
            s_hist[qq]++;
        }
    }

    /* ---- pass 2: the PAL_MAX most frequent colours become the palette ---- */
    uint16_t pal[PAL_MAX];
    int npal = 0;
    for (int n = 0; n < PAL_MAX; n++) {
        int best = -1;
        uint32_t bestc = 0;
        for (int i = 0; i < QMAX; i++) {
            if (s_hist[i] > bestc) {
                bestc = s_hist[i];
                best  = i;
            }
        }
        if (best < 0 || bestc == 0) {
            break;
        }
        pal[npal++] = (uint16_t)best;
        s_hist[best] = 0;
    }
    if (npal == 0) {
        printf("===SNAP FAIL empty frame===\n");
        heap_caps_free(q);
        heap_caps_free(buf);
        return;
    }

    /* ---- pass 3: every one of the 4096 buckets -> nearest palette index -- */
    for (int i = 0; i < QMAX; i++) {
        const uint32_t c = un444((uint16_t)i);
        const int cr = (int)((c >> 16) & 0xFFu);
        const int cg = (int)((c >> 8) & 0xFFu);
        const int cb = (int)(c & 0xFFu);
        int bi = 0;
        uint32_t bd = 0xFFFFFFFFu;

        for (int k = 0; k < npal; k++) {
            const uint32_t p = un444(pal[k]);
            const int dr = cr - (int)((p >> 16) & 0xFFu);
            const int dg = cg - (int)((p >> 8) & 0xFFu);
            const int db = cb - (int)(p & 0xFFu);
            const uint32_t d = (uint32_t)(dr * dr * 3 + dg * dg * 4 + db * db * 2);
            if (d < bd) {
                bd = d;
                bi = k;
            }
        }
        s_lut[i] = (uint8_t)bi;
    }

    /* ---- emit ---- */
    printf("===SNAP begin w=%d h=%d step=%d cols=%d rows=%d pal=%d===\n",
           W, H, step, CW, CH, npal);
    for (int i = 0; i < npal; i++) {
        printf("P%02d=%06X\n", i, (unsigned)un444(pal[i]));
    }

    static char line[32 + 1024];
    static const char IDX_CH[] = "0123456789ABCDE";   /* PAL_MAX == 15 */

    for (int by = 0; by < CH; by++) {
        int p = snprintf(line, sizeof(line) - 1, "R%03d:", by);
        uint32_t chk = 0;

        for (int bx = 0; bx < CW; bx++) {
            const uint8_t idx = s_lut[q[by * CW + bx]];
            chk = chk * 31u + idx;
            /* Must go through the table, NOT '0' + idx: '0' + 10..14 yields
             * ':' ';' '<' '=' '>', which looks like a perfectly plausible row
             * of 814 characters but is not hex, so the host silently drops
             * the whole row. */
            line[p++] = IDX_CH[idx];
        }
        line[p] = '\0';
        printf("%s|%08X\n", line, (unsigned)chk);
    }
    printf("===SNAP end===\n");

    heap_caps_free(q);
    heap_caps_free(buf);
}

/* ------------------------------------------------------------------ run - */
static void probe_run(void)
{
    printf("\n===DBGSCREEN begin===\n");

    weigh_model_reset(WEIGH_CH_A);
    weigh_model_reset(WEIGH_CH_B);

    /* --- frame 0: row A = the requirement-sheet specimen, all checks pass.
     * Row B keeps only a *failed* zero read, so the same shot also shows the
     * two other cell states side by side: blank (never read) and "-" (read
     * timed out). ------------------------------------------------------- */
    weigh_model_set_raw(WEIGH_CH_A, ITEM_ZERO, 326);
    weigh_model_set_raw(WEIGH_CH_A, ITEM_HOOK, 593);
    weigh_model_set_raw(WEIGH_CH_A, ITEM_G4K, 40568);
    weigh_model_set_raw(WEIGH_CH_A, ITEM_G500, 5582);

    weigh_model_fail_raw(WEIGH_CH_B, ITEM_ZERO);

    ui_weigh_refresh_all();
    probe_text_fit();
    probe_glyphs();
    snap_emit(1);

    /* --- frame 1: worst case.  Row B gets the widest strings the panel can
     * ever hold (7-char -200000) and fails all three checks. ------------- */
    weigh_model_set_raw(WEIGH_CH_B, ITEM_ZERO, -40568);
    weigh_model_set_raw(WEIGH_CH_B, ITEM_HOOK, 593);
    weigh_model_set_raw(WEIGH_CH_B, ITEM_G4K, -39407);
    weigh_model_set_raw(WEIGH_CH_B, ITEM_G500, 5582);

    ui_weigh_refresh_all();
    probe_text_fit();
    snap_emit(1);

    /* --- frame 2: 重置 both rows -> the power-on state, all cells blank --- */
    weigh_model_reset(WEIGH_CH_A);
    weigh_model_reset(WEIGH_CH_B);
    ui_weigh_refresh_all();
    snap_emit(1);

    printf("===DBGSCREEN end===\n");
}

static void dbg_task(void *arg)
{
    (void)arg;
    vTaskDelay(pdMS_TO_TICKS(3000));

    if (lvgl_port_lock(-1)) {
        probe_run();
        lvgl_port_unlock();
    } else {
        ESP_LOGE(TAG, "could not take the LVGL lock");
    }

    /* make sure the tail of the dump has really left the chip before the
     * host is told the capture is over */
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(1000));
    vTaskDelete(NULL);
}

void dbg_screen_start(void)
{
    if (xTaskCreate(dbg_task, "dbg_screen", 6144, NULL, 4, NULL) != pdPASS) {
        ESP_LOGE(TAG, "cannot start the dump task");
    }
}
