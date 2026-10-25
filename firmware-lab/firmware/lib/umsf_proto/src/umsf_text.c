/* umsf_text.c - see umsf_text.h */
#include "umsf_text.h"
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

char *umsf_text_flag_letters(uint8_t cf, char *out) {
    static const struct { uint8_t bit; char c; } m[] = {
        {UMSF_CH_T, 'T'}, {UMSF_CH_PPG, 'P'}, {UMSF_CH_MOTION, 'M'},
        {UMSF_CH_HR_SYNTHETIC, 'H'}, {UMSF_CH_GSR, 'G'}, {UMSF_CH_SOS_ACTIVE, 'S'}};
    size_t i, n = 0;
    for (i = 0; i < sizeof m / sizeof m[0]; ++i)
        if (cf & m[i].bit) out[n++] = m[i].c;
    out[n] = '\0';
    return out;
}

/* Small appender that tracks overflow. */
typedef struct { char *p; size_t cap, n; int bad; } sb_t;

#ifdef __GNUC__
static void sb_fmt(sb_t *b, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
#endif
static void sb_fmt(sb_t *b, const char *fmt, ...) {
    va_list ap;
    int w;
    if (b->bad) return;
    va_start(ap, fmt);
    w = vsnprintf(b->p + b->n, b->cap - b->n, fmt, ap);
    va_end(ap);
    if (w < 0 || (size_t)w >= b->cap - b->n) { b->bad = 1; return; }
    b->n += (size_t)w;
}
static void f_u16(sb_t *b, uint16_t v) { if (v == UMSF_NULL_U16) sb_fmt(b, ","); else sb_fmt(b, ",%u", (unsigned)v); }
static void f_i16(sb_t *b, int16_t v)  { if (v == UMSF_NULL_I16) sb_fmt(b, ","); else sb_fmt(b, ",%d", (int)v); }
static void f_u32(sb_t *b, uint32_t v) { if (v == UMSF_NULL_U32) sb_fmt(b, ","); else sb_fmt(b, ",%lu", (unsigned long)v); }

int umsf_text_line(const char *gw_id, uint32_t gw_ms, const umsf_frame_t *f, char *out, size_t cap) {
    sb_t b = {out, cap, 0, 0};
    char kind;
    const umsf_header_t *h = &f->hdr;
    if (!out || cap == 0) return -1;
    switch (h->frame_type) {
    case UMSF_FT_PHYSIO_FEATURE: kind = 'F'; break;
    case UMSF_FT_STATION_STATE:  kind = 'S'; break;
    case UMSF_FT_EVENT:          kind = 'E'; break;
    default: return -1;
    }
    sb_fmt(&b, "RX,%s,%lu,%c,%.4s,%u,%lu,%lu", gw_id, (unsigned long)gw_ms, kind, h->device_id,
           (unsigned)h->boot_id, (unsigned long)h->sequence, (unsigned long)h->node_time_ms);
    if (kind == 'F') {
        const umsf_physio_t *p = &f->u.physio;
        char letters[8];
        f_i16(&b, p->skin_temp);
        f_u32(&b, p->ppg_ir_mean);
        f_u16(&b, p->motion_rms_mg);
        if (p->hr == UMSF_NULL_U16) sb_fmt(&b, ",");
        else sb_fmt(&b, ",%u", (unsigned)((p->hr + 5u) / 10u));
        sb_fmt(&b, ",%s", umsf_text_flag_letters(p->channel_flags, letters));
    } else if (kind == 'S') {
        const umsf_station_t *s = &f->u.station;
        f_u16(&b, s->vib_peak_cg);
        f_i16(&b, s->tilt_ddeg);
        f_u16(&b, s->pressure_dhpa);
        f_i16(&b, s->temp);
        f_u16(&b, s->gas_mv);
        f_u16(&b, s->sound_index);
        sb_fmt(&b, ",%02X", (unsigned)s->flags);
    } else {
        const umsf_event_t *e = &f->u.event;
        const char *name = umsf_event_type_name(e->event_type);
        if (name) sb_fmt(&b, ",%s", name);
        else sb_fmt(&b, ",unknown_%u", (unsigned)e->event_type);
        sb_fmt(&b, ",%u,%ld", (unsigned)e->level, (long)e->value);
    }
    if (b.bad) { out[0] = '\0'; return -1; }
    return (int)b.n;
}
