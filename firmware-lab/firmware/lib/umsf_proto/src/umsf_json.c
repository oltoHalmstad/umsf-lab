/* umsf_json.c - see umsf_json.h */
#include "umsf_json.h"
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

typedef struct { char *p; size_t cap, n; int bad; } jb_t;

#ifdef __GNUC__
static void jf(jb_t *b, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
#endif
static void jf(jb_t *b, const char *fmt, ...) {
    va_list ap;
    int w;
    if (b->bad) return;
    va_start(ap, fmt);
    w = vsnprintf(b->p + b->n, b->cap - b->n, fmt, ap);
    va_end(ap);
    if (w < 0 || (size_t)w >= b->cap - b->n) { b->bad = 1; return; }
    b->n += (size_t)w;
}

/* key prefix: ,"key": (first key has no comma) */
static void key(jb_t *b, const char *k) { jf(b, "%s\"%s\":", b->n > 1 ? "," : "", k); }

static void jval_str(jb_t *b, const char *v) {
    if (!v) { jf(b, "null"); return; }
    jf(b, "\"");
    for (; *v; ++v) {
        unsigned char c = (unsigned char)*v;
        if (c == '"' || c == '\\') jf(b, "\\%c", c);
        else if (c < 0x20) jf(b, "\\u%04x", c);
        else jf(b, "%c", c);
    }
    jf(b, "\"");
}
static void jstr(jb_t *b, const char *k, const char *v) { key(b, k); jval_str(b, v); }
static void jnull(jb_t *b, const char *k) { key(b, k); jf(b, "null"); }
static void jint(jb_t *b, const char *k, long long v) { key(b, k); jf(b, "%lld", v); }
static void jbool(jb_t *b, const char *k, int v) { key(b, k); jf(b, v ? "true" : "false"); }

/* Integer v scaled by 10^dec, printed exactly, e.g. (2219,2) -> 22.19, (-5,1) -> -0.5 */
static void jscaled(jb_t *b, const char *k, long long v, int dec) {
    long long div = 1, ip, fp;
    int i;
    key(b, k);
    for (i = 0; i < dec; ++i) div *= 10;
    if (v < 0) { jf(b, "-"); v = -v; }
    ip = v / div;
    fp = v % div;
    if (dec) jf(b, "%lld.%0*lld", ip, dec, fp);
    else jf(b, "%lld", ip);
}

static void jtime(jb_t *b, const char *k, int64_t ms) {
    char t[32];
    if (ms < 0 || !umsf_iso8601_ms(ms, t, sizeof t)) jnull(b, k);
    else jstr(b, k, t);
}

static void junc(jb_t *b, int32_t ms) {
    if (ms < 0) jnull(b, "time_uncertainty_s");
    else jscaled(b, "time_uncertainty_s", ms, 3);
}

static void jhex(jb_t *b, const uint8_t *raw, size_t len) {
    size_t i;
    if (!raw) return;
    key(b, "frame_hex");
    jf(b, "\"");
    for (i = 0; i < len; ++i) jf(b, "%02x", raw[i]);
    jf(b, "\"");
}

static void dev_id(const umsf_header_t *h, char out[5]) {
    memcpy(out, h->device_id, 4);
    out[4] = '\0';
}

static int finish(jb_t *b) {
    jf(b, "}");
    if (b->bad) { if (b->cap) b->p[0] = '\0'; return -1; }
    return (int)b->n;
}

void umsf_json_ctx_init(umsf_json_ctx_t *c) {
    memset(c, 0, sizeof(*c));
    c->data_origin = "measured";
    c->measured_at_ms = UMSF_TIME_UNKNOWN;
    c->received_at_ms = UMSF_TIME_UNKNOWN;
    c->time_uncertainty_ms = -1;
}

static void common_head(jb_t *b, const char *schema, const umsf_json_ctx_t *c) {
    jf(b, "{");
    jstr(b, "schema_version", schema);
    jstr(b, "data_origin", c->data_origin);
    jstr(b, "scenario_id", c->scenario_id);
    jstr(b, "site_id", c->site_id);
}

int umsf_json_physio(const umsf_json_ctx_t *c, const umsf_frame_t *f, const uint8_t *raw, size_t raw_len,
                     char *out, size_t cap) {
    jb_t b = {out, cap, 0, 0};
    const umsf_physio_t *p = &f->u.physio;
    char id[5];
    if (f->hdr.frame_type != UMSF_FT_PHYSIO_FEATURE || !cap) return -1;
    dev_id(&f->hdr, id);
    common_head(&b, "1.0", c);
    jstr(&b, "device_id", id);
    jint(&b, "boot_id", f->hdr.boot_id);
    jint(&b, "sequence", f->hdr.sequence);
    jtime(&b, "measured_at", c->measured_at_ms);
    jtime(&b, "received_at", c->received_at_ms);
    if (p->hr == UMSF_NULL_U16) jnull(&b, "hr_bpm"); else jscaled(&b, "hr_bpm", p->hr, 1);
    if (p->spo2 == UMSF_NULL_U16) jnull(&b, "spo2_pct"); else jscaled(&b, "spo2_pct", p->spo2, 1);
    if (p->skin_temp == UMSF_NULL_I16) jnull(&b, "skin_temp_c"); else jscaled(&b, "skin_temp_c", p->skin_temp, 2);
    if (p->motion_rms_mg == UMSF_NULL_U16) jnull(&b, "motion_rms_g"); else jscaled(&b, "motion_rms_g", p->motion_rms_mg, 3);
    if (p->quality_pct == UMSF_NULL_U8) jnull(&b, "quality"); else jscaled(&b, "quality", p->quality_pct, 2);
    if (p->battery_pct == UMSF_NULL_U8) jnull(&b, "battery_pct"); else jint(&b, "battery_pct", p->battery_pct);
    /* optional extension keys */
    if (c->gateway_id) jstr(&b, "gateway_id", c->gateway_id);
    if (c->zone_id) jstr(&b, "zone_id", c->zone_id);
    if (c->worker_pseudonym) jstr(&b, "worker_pseudonym", c->worker_pseudonym);
    if (p->ppg_ir_mean == UMSF_NULL_U32) jnull(&b, "ppg_ir"); else jint(&b, "ppg_ir", p->ppg_ir_mean);
    jint(&b, "channel_flags", p->channel_flags);
    jint(&b, "artifact_flags", p->artifact_flags);
    jbool(&b, "hr_synthetic", (p->channel_flags & UMSF_CH_HR_SYNTHETIC) != 0);
    jint(&b, "fw_build", p->fw_build);
    junc(&b, c->time_uncertainty_ms);
    jhex(&b, raw, raw_len);
    return finish(&b);
}

int umsf_json_station(const umsf_json_ctx_t *c, const umsf_frame_t *f, const uint8_t *raw, size_t raw_len,
                      char *out, size_t cap) {
    jb_t b = {out, cap, 0, 0};
    const umsf_station_t *s = &f->u.station;
    char id[5];
    if (f->hdr.frame_type != UMSF_FT_STATION_STATE || !cap) return -1;
    dev_id(&f->hdr, id);
    common_head(&b, "st-1.0", c);
    jstr(&b, "zone_id", c->zone_id);
    jstr(&b, "device_id", id);
    jint(&b, "boot_id", f->hdr.boot_id);
    jint(&b, "sequence", f->hdr.sequence);
    jtime(&b, "measured_at", c->measured_at_ms);
    jtime(&b, "received_at", c->received_at_ms);
    if (s->vib_peak_cg == UMSF_NULL_U16) jnull(&b, "vib_peak_g"); else jscaled(&b, "vib_peak_g", s->vib_peak_cg, 2);
    if (s->accel_rms_mg == UMSF_NULL_U16) jnull(&b, "accel_rms_g"); else jscaled(&b, "accel_rms_g", s->accel_rms_mg, 3);
    if (s->tilt_ddeg == UMSF_NULL_I16) jnull(&b, "tilt_deg"); else jscaled(&b, "tilt_deg", s->tilt_ddeg, 1);
    if (s->tilt_delta_ddeg == UMSF_NULL_I16) jnull(&b, "tilt_delta_deg"); else jscaled(&b, "tilt_delta_deg", s->tilt_delta_ddeg, 1);
    if (s->pressure_dhpa == UMSF_NULL_U16) jnull(&b, "pressure_hpa"); else jscaled(&b, "pressure_hpa", s->pressure_dhpa, 1);
    if (s->pressure_delta_pa == UMSF_NULL_I16) jnull(&b, "pressure_delta_pa"); else jint(&b, "pressure_delta_pa", s->pressure_delta_pa);
    if (s->temp == UMSF_NULL_I16) jnull(&b, "temp_c"); else jscaled(&b, "temp_c", s->temp, 2);
    if (s->gas_mv == UMSF_NULL_U16) jnull(&b, "gas_v"); else jscaled(&b, "gas_v", s->gas_mv, 3);
    if (s->sound_index == UMSF_NULL_U16) jnull(&b, "sound_index"); else jint(&b, "sound_index", s->sound_index);
    if (s->sensor_flags & UMSF_SEN_PIR_OK) jbool(&b, "pir_presence", (s->flags & UMSF_SF_PIR_PRESENCE) != 0);
    else jnull(&b, "pir_presence");
    jbool(&b, "sos", (s->flags & UMSF_SF_SOS_ACTIVE) != 0);
    jbool(&b, "attachment_verified", c->attachment_verified && !(s->flags & UMSF_SF_ATTACHMENT_UNCERTAIN));
    if (s->quality_pct == UMSF_NULL_U8) jnull(&b, "quality"); else jscaled(&b, "quality", s->quality_pct, 2);
    if (s->battery_pct == UMSF_NULL_U8) jnull(&b, "battery_pct"); else jint(&b, "battery_pct", s->battery_pct);
    if (c->gateway_id) jstr(&b, "gateway_id", c->gateway_id);
    jint(&b, "flags", s->flags);
    jint(&b, "sensor_flags", s->sensor_flags);
    jint(&b, "fw_build", s->fw_build);
    jhex(&b, raw, raw_len);
    return finish(&b);
}

int umsf_json_event(const umsf_json_ctx_t *c, const umsf_frame_t *f, const uint8_t *raw, size_t raw_len,
                    char *out, size_t cap) {
    jb_t b = {out, cap, 0, 0};
    const umsf_event_t *e = &f->u.event;
    char id[5], eid[96], prov[64];
    const char *sc = umsf_source_class_name(f->hdr.source_class);
    if (f->hdr.frame_type != UMSF_FT_EVENT || !cap) return -1;
    dev_id(&f->hdr, id);
    /* Event identity follows the frame identity (site, originator, boot, seq), so a gateway-generated
     * event never collides with the subject node's own identities. */
    snprintf(eid, sizeof eid, "%s:%s:%u:%lu", c->site_id ? c->site_id : "", id,
             (unsigned)f->hdr.boot_id, (unsigned long)f->hdr.sequence);
    snprintf(prov, sizeof prov, "%s:%s", sc ? sc : "unknown", id);
    common_head(&b, "ev-1.0", c);
    jstr(&b, "zone_id", c->zone_id);
    jstr(&b, "event_id", eid);
    jstr(&b, "source_class", sc);
    jstr(&b, "device_id", c->subject_device_id ? c->subject_device_id : id);
    jstr(&b, "event_type", umsf_event_type_name(e->event_type));
    jstr(&b, "level", umsf_level_name(e->level));
    jscaled(&b, "value", e->value, 3);
    jstr(&b, "unit", umsf_event_unit(e->event_type));
    jtime(&b, "observed_at", c->measured_at_ms);
    jtime(&b, "reported_at", c->received_at_ms);
    junc(&b, c->time_uncertainty_ms);
    jint(&b, "rule_version", e->rule_version);
    jnull(&b, "quality");
    jstr(&b, "ack_state", "unacknowledged");
    key(&b, "provenance");
    jf(&b, "{\"source\":");
    jval_str(&b, prov);
    jf(&b, ",\"method\":");
    jval_str(&b, c->method ? c->method : "umsf-ble-firmware threshold rule (uncalibrated)");
    jf(&b, "}");
    if (c->gateway_id) jstr(&b, "gateway_id", c->gateway_id);
    jint(&b, "boot_id", f->hdr.boot_id);
    jint(&b, "sequence", f->hdr.sequence);
    jhex(&b, raw, raw_len);
    return finish(&b);
}

int umsf_json_node_status(const umsf_json_ctx_t *c, const umsf_frame_t *f, char *out, size_t cap) {
    jb_t b = {out, cap, 0, 0};
    const umsf_status_t *s = &f->u.status;
    char id[5];
    if (f->hdr.frame_type != UMSF_FT_STATUS || !cap) return -1;
    dev_id(&f->hdr, id);
    jf(&b, "{");
    jstr(&b, "kind", "node_status");
    jstr(&b, "site_id", c->site_id);
    jstr(&b, "gateway_id", c->gateway_id);
    jstr(&b, "device_id", id);
    jstr(&b, "source_class", umsf_source_class_name(f->hdr.source_class));
    jint(&b, "boot_id", f->hdr.boot_id);
    jtime(&b, "received_at", c->received_at_ms);
    if (s->battery_pct == UMSF_NULL_U8) jnull(&b, "battery_pct"); else jint(&b, "battery_pct", s->battery_pct);
    jint(&b, "buffered_records", s->buffered_records);
    jint(&b, "evicted_total", s->evicted_total);
    jint(&b, "sent_total", s->sent_total);
    jint(&b, "acked_up_to_seq", s->acked_up_to_seq);
    jint(&b, "fw_build", s->fw_build);
    jint(&b, "sensor_flags", s->sensor_flags);
    if (s->rssi_neg == UMSF_NULL_U8) jnull(&b, "rssi_dbm"); else jint(&b, "rssi_dbm", -(int)s->rssi_neg);
    return finish(&b);
}

int umsf_json_record(const umsf_json_ctx_t *c, const umsf_frame_t *f, const uint8_t *raw, size_t raw_len,
                     char *out, size_t cap) {
    switch (f->hdr.frame_type) {
    case UMSF_FT_PHYSIO_FEATURE: return umsf_json_physio(c, f, raw, raw_len, out, cap);
    case UMSF_FT_STATION_STATE:  return umsf_json_station(c, f, raw, raw_len, out, cap);
    case UMSF_FT_EVENT:          return umsf_json_event(c, f, raw, raw_len, out, cap);
    default:                     return -1;
    }
}

/* civil_from_days (H. Hinnant), proleptic Gregorian, days since 1970-01-01 */
static void civil(long long z, int *y, unsigned *m, unsigned *d) {
    long long era, yy;
    unsigned doe, yoe, doy, mp;
    z += 719468;
    era = (z >= 0 ? z : z - 146096) / 146097;
    doe = (unsigned)(z - era * 146097);
    yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    yy = (long long)yoe + era * 400;
    doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    mp = (5 * doy + 2) / 153;
    *d = doy - (153 * mp + 2) / 5 + 1;
    *m = mp < 10 ? mp + 3 : mp - 9;
    *y = (int)(yy + (*m <= 2));
}

char *umsf_iso8601_ms(int64_t ms, char *out, size_t cap) {
    long long days, rem;
    int y;
    unsigned mo, d;
    if (ms < 0 || cap < 25) return NULL;
    days = ms / 86400000LL;
    rem = ms % 86400000LL;
    civil(days, &y, &mo, &d);
    snprintf(out, cap, "%04d-%02u-%02uT%02u:%02u:%02u.%03uZ", y, mo, d, (unsigned)(rem / 3600000),
             (unsigned)(rem / 60000 % 60), (unsigned)(rem / 1000 % 60), (unsigned)(rem % 1000));
    return out;
}

/* ---- time map ---- */
void umsf_timemap_init(umsf_timemap_t *t) {
    memset(t, 0, sizeof(*t));
    t->latency_allowance_ms = 250;
    t->drift_ppm = 100;
    t->window_ms = 600000;
}

void umsf_timemap_observe(umsf_timemap_t *t, uint16_t boot_id, uint32_t seq, uint32_t node_ms, int64_t rx_local) {
    int64_t off = rx_local - (int64_t)node_ms;
    if (!t->valid || t->boot_id != boot_id) {
        t->valid = 1;
        t->boot_id = boot_id;
        t->last_seq = seq;
        t->min_off = t->max_off = off;
        t->win_start_local = rx_local;
        t->next_n = 0;
        return;
    }
    if (seq <= t->last_seq) return; /* resend: not a live observation */
    t->last_seq = seq;
    if (off < t->min_off) t->min_off = off;
    if (off > t->max_off) t->max_off = off;
    if (t->next_n == 0 || off < t->next_min) t->next_min = off;
    if (t->next_n == 0 || off > t->next_max) t->next_max = off;
    ++t->next_n;
    if (rx_local - t->win_start_local >= (int64_t)t->window_ms && t->next_n >= 3) {
        /* re-anchor on the most recent window so node-clock drift does not accumulate */
        t->min_off = t->next_min;
        t->max_off = t->next_max;
        t->win_start_local = rx_local;
        t->next_n = 0;
    }
}

int umsf_timemap_map(const umsf_timemap_t *t, uint16_t boot_id, uint32_t node_ms, int64_t now_local,
                     int64_t *local_ms, uint32_t *unc_ms) {
    int64_t age;
    if (!t->valid || t->boot_id != boot_id) return -1;
    *local_ms = (int64_t)node_ms + t->min_off;
    age = now_local - t->win_start_local;
    if (age < 0) age = -age;
    *unc_ms = (uint32_t)((t->max_off - t->min_off) + t->latency_allowance_ms +
                         (age * (int64_t)t->drift_ppm) / 1000000);
    return 0;
}
