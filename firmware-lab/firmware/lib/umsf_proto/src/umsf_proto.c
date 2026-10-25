/* umsf_proto.c - frame codec, see umsf_proto.h */
#include "umsf_proto.h"
#include <string.h>

/* ---- little-endian helpers ---- */
static void put_u16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}
static uint16_t get_u16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }
static uint32_t get_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
#define put_i16(p, v) put_u16((p), (uint16_t)(int16_t)(v))
#define put_i32(p, v) put_u32((p), (uint32_t)(int32_t)(v))
#define get_i16(p) ((int16_t)get_u16(p))
#define get_i32(p) ((int32_t)get_u32(p))

uint16_t umsf_crc16_update(uint16_t crc, const uint8_t *data, size_t len) {
    size_t i;
    int b;
    for (i = 0; i < len; ++i) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (b = 0; b < 8; ++b)
            crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
    }
    return crc;
}

uint16_t umsf_crc16(const uint8_t *data, size_t len) { return umsf_crc16_update(0xFFFFu, data, len); }

size_t umsf_payload_len(uint8_t ft) {
    switch (ft) {
    case UMSF_FT_PHYSIO_FEATURE: return UMSF_PL_PHYSIO;
    case UMSF_FT_STATION_STATE:  return UMSF_PL_STATION;
    case UMSF_FT_EVENT:          return UMSF_PL_EVENT;
    case UMSF_FT_STATUS:         return UMSF_PL_STATUS;
    case UMSF_FT_ACK:            return UMSF_PL_ACK;
    case UMSF_FT_CONFIG:         return UMSF_PL_CONFIG;
    default:                     return 0;
    }
}

size_t umsf_frame_len(uint8_t ft) {
    size_t pl = umsf_payload_len(ft);
    return pl ? UMSF_HDR_LEN + pl + UMSF_CRC_LEN : 0;
}

void umsf_header_init(umsf_header_t *h, uint8_t sc, uint8_t ft, const char *dev,
                      uint16_t boot_id, uint32_t seq, uint32_t node_ms) {
    size_t i;
    memset(h, 0, sizeof(*h));
    h->magic = UMSF_MAGIC;
    h->version = UMSF_VERSION;
    h->source_class = sc;
    h->frame_type = ft;
    for (i = 0; dev && i < 4 && dev[i]; ++i) h->device_id[i] = dev[i];
    h->boot_id = boot_id;
    h->sequence = seq;
    h->node_time_ms = node_ms;
}

void umsf_physio_set_null(umsf_physio_t *p) {
    p->skin_temp = UMSF_NULL_I16;
    p->hr = UMSF_NULL_U16;
    p->spo2 = UMSF_NULL_U16;
    p->ppg_ir_mean = UMSF_NULL_U32;
    p->ppg_red_mean_div16 = UMSF_NULL_U16;
    p->ppg_valid_permille = UMSF_NULL_U16;
    p->motion_rms_mg = UMSF_NULL_U16;
    p->gsr_mv = UMSF_NULL_U16;
    p->quality_pct = UMSF_NULL_U8;
    p->battery_pct = UMSF_NULL_U8;
    p->channel_flags = 0;
    p->artifact_flags = 0;
    p->n_ppg_samples = 0;
    p->n_imu_samples = 0;
    p->window_ms = 0;
    p->fw_build = 0;
}

void umsf_station_set_null(umsf_station_t *s) {
    s->vib_peak_cg = UMSF_NULL_U16;
    s->accel_rms_mg = UMSF_NULL_U16;
    s->tilt_ddeg = UMSF_NULL_I16;
    s->tilt_delta_ddeg = UMSF_NULL_I16;
    s->pressure_dhpa = UMSF_NULL_U16;
    s->pressure_delta_pa = UMSF_NULL_I16;
    s->temp = UMSF_NULL_I16;
    s->gas_mv = UMSF_NULL_U16;
    s->gas_baseline_mv = UMSF_NULL_U16;
    s->sound_index = UMSF_NULL_U16;
    s->flags = 0;
    s->quality_pct = UMSF_NULL_U8;
    s->battery_pct = UMSF_NULL_U8;
    s->sensor_flags = 0;
    s->n_imu_samples = 0;
    s->window_ms = 0;
    s->zone_code = 0;
    s->fw_build = 0;
}

void umsf_status_set_null(umsf_status_t *s) {
    memset(s, 0, sizeof(*s));
    s->battery_pct = UMSF_NULL_U8;
    s->rssi_neg = UMSF_NULL_U8;
}

static void enc_payload(const umsf_frame_t *f, uint8_t *p) {
    switch (f->hdr.frame_type) {
    case UMSF_FT_PHYSIO_FEATURE: {
        const umsf_physio_t *v = &f->u.physio;
        put_i16(p + 0, v->skin_temp);   put_u16(p + 2, v->hr);
        put_u16(p + 4, v->spo2);        put_u32(p + 6, v->ppg_ir_mean);
        put_u16(p + 10, v->ppg_red_mean_div16); put_u16(p + 12, v->ppg_valid_permille);
        put_u16(p + 14, v->motion_rms_mg);      put_u16(p + 16, v->gsr_mv);
        p[18] = v->quality_pct; p[19] = v->battery_pct;
        p[20] = v->channel_flags; p[21] = v->artifact_flags;
        put_u16(p + 22, v->n_ppg_samples); put_u16(p + 24, v->n_imu_samples);
        put_u16(p + 26, v->window_ms);     put_u16(p + 28, v->fw_build);
        break;
    }
    case UMSF_FT_STATION_STATE: {
        const umsf_station_t *v = &f->u.station;
        put_u16(p + 0, v->vib_peak_cg);  put_u16(p + 2, v->accel_rms_mg);
        put_i16(p + 4, v->tilt_ddeg);    put_i16(p + 6, v->tilt_delta_ddeg);
        put_u16(p + 8, v->pressure_dhpa); put_i16(p + 10, v->pressure_delta_pa);
        put_i16(p + 12, v->temp);        put_u16(p + 14, v->gas_mv);
        put_u16(p + 16, v->gas_baseline_mv); put_u16(p + 18, v->sound_index);
        p[20] = v->flags; p[21] = v->quality_pct; p[22] = v->battery_pct; p[23] = v->sensor_flags;
        put_u16(p + 24, v->n_imu_samples); put_u16(p + 26, v->window_ms);
        put_u16(p + 28, v->zone_code);     put_u16(p + 30, v->fw_build);
        break;
    }
    case UMSF_FT_EVENT: {
        const umsf_event_t *v = &f->u.event;
        p[0] = v->event_type; p[1] = v->level;
        put_i32(p + 2, v->value); put_u16(p + 6, v->rule_version);
        put_u16(p + 8, v->zone_code); put_u16(p + 10, v->related_seq_lo);
        break;
    }
    case UMSF_FT_STATUS: {
        const umsf_status_t *v = &f->u.status;
        p[0] = v->battery_pct; p[1] = v->buffered_records;
        put_u16(p + 2, v->evicted_total); put_u32(p + 4, v->sent_total);
        put_u32(p + 8, v->acked_up_to_seq); put_u16(p + 12, v->fw_build);
        p[14] = v->sensor_flags; p[15] = v->rssi_neg;
        break;
    }
    case UMSF_FT_ACK: {
        const umsf_ack_t *v = &f->u.ack;
        put_u16(p + 0, v->target_boot_id); put_u16(p + 2, v->reserved); put_u32(p + 4, v->ack_up_to_seq);
        break;
    }
    case UMSF_FT_CONFIG: {
        const umsf_config_t *v = &f->u.config;
        put_u16(p + 0, v->zone_code); put_u16(p + 2, v->feature_window_ms);
        p[4] = v->sample_profile; p[5] = v->synthetic_hr_enabled; put_u16(p + 6, v->reserved);
        break;
    }
    default: break;
    }
}

static void dec_payload(uint8_t ft, const uint8_t *p, umsf_frame_t *f) {
    switch (ft) {
    case UMSF_FT_PHYSIO_FEATURE: {
        umsf_physio_t *v = &f->u.physio;
        v->skin_temp = get_i16(p + 0);  v->hr = get_u16(p + 2);
        v->spo2 = get_u16(p + 4);       v->ppg_ir_mean = get_u32(p + 6);
        v->ppg_red_mean_div16 = get_u16(p + 10); v->ppg_valid_permille = get_u16(p + 12);
        v->motion_rms_mg = get_u16(p + 14);      v->gsr_mv = get_u16(p + 16);
        v->quality_pct = p[18]; v->battery_pct = p[19];
        v->channel_flags = p[20]; v->artifact_flags = p[21];
        v->n_ppg_samples = get_u16(p + 22); v->n_imu_samples = get_u16(p + 24);
        v->window_ms = get_u16(p + 26);     v->fw_build = get_u16(p + 28);
        break;
    }
    case UMSF_FT_STATION_STATE: {
        umsf_station_t *v = &f->u.station;
        v->vib_peak_cg = get_u16(p + 0);  v->accel_rms_mg = get_u16(p + 2);
        v->tilt_ddeg = get_i16(p + 4);    v->tilt_delta_ddeg = get_i16(p + 6);
        v->pressure_dhpa = get_u16(p + 8); v->pressure_delta_pa = get_i16(p + 10);
        v->temp = get_i16(p + 12);        v->gas_mv = get_u16(p + 14);
        v->gas_baseline_mv = get_u16(p + 16); v->sound_index = get_u16(p + 18);
        v->flags = p[20]; v->quality_pct = p[21]; v->battery_pct = p[22]; v->sensor_flags = p[23];
        v->n_imu_samples = get_u16(p + 24); v->window_ms = get_u16(p + 26);
        v->zone_code = get_u16(p + 28);     v->fw_build = get_u16(p + 30);
        break;
    }
    case UMSF_FT_EVENT: {
        umsf_event_t *v = &f->u.event;
        v->event_type = p[0]; v->level = p[1];
        v->value = get_i32(p + 2); v->rule_version = get_u16(p + 6);
        v->zone_code = get_u16(p + 8); v->related_seq_lo = get_u16(p + 10);
        break;
    }
    case UMSF_FT_STATUS: {
        umsf_status_t *v = &f->u.status;
        v->battery_pct = p[0]; v->buffered_records = p[1];
        v->evicted_total = get_u16(p + 2); v->sent_total = get_u32(p + 4);
        v->acked_up_to_seq = get_u32(p + 8); v->fw_build = get_u16(p + 12);
        v->sensor_flags = p[14]; v->rssi_neg = p[15];
        break;
    }
    case UMSF_FT_ACK: {
        umsf_ack_t *v = &f->u.ack;
        v->target_boot_id = get_u16(p + 0); v->reserved = get_u16(p + 2); v->ack_up_to_seq = get_u32(p + 4);
        break;
    }
    case UMSF_FT_CONFIG: {
        umsf_config_t *v = &f->u.config;
        v->zone_code = get_u16(p + 0); v->feature_window_ms = get_u16(p + 2);
        v->sample_profile = p[4]; v->synthetic_hr_enabled = p[5]; v->reserved = get_u16(p + 6);
        break;
    }
    default: break;
    }
}

size_t umsf_encode(const umsf_frame_t *f, uint8_t *out, size_t cap) {
    size_t pl, total, i;
    uint16_t crc;
    if (!f || !out) return 0;
    pl = umsf_payload_len(f->hdr.frame_type);
    total = UMSF_HDR_LEN + pl + UMSF_CRC_LEN;
    if (!pl || cap < total) return 0;
    out[0] = UMSF_MAGIC;
    out[1] = UMSF_VERSION;
    out[2] = f->hdr.source_class;
    out[3] = f->hdr.frame_type;
    for (i = 0; i < 4; ++i) out[4 + i] = (uint8_t)f->hdr.device_id[i];
    put_u16(out + 8, f->hdr.boot_id);
    put_u32(out + 10, f->hdr.sequence);
    put_u32(out + 14, f->hdr.node_time_ms);
    enc_payload(f, out + UMSF_HDR_LEN);
    crc = umsf_crc16(out, UMSF_HDR_LEN + pl);
    put_u16(out + UMSF_HDR_LEN + pl, crc);
    return total;
}

int umsf_decode(const uint8_t *buf, size_t len, umsf_frame_t *f) {
    size_t pl, total, i;
    if (!buf || !f) return UMSF_ERR_ARG;
    if (len < UMSF_HDR_LEN) return UMSF_ERR_SHORT;
    if (buf[0] != UMSF_MAGIC) return UMSF_ERR_MAGIC;
    if (buf[1] != UMSF_VERSION) return UMSF_ERR_VERSION;
    pl = umsf_payload_len(buf[3]);
    if (!pl) return UMSF_ERR_TYPE;
    total = UMSF_HDR_LEN + pl + UMSF_CRC_LEN;
    if (len < total) return UMSF_ERR_SHORT;
    if (len > total) return UMSF_ERR_LENGTH;
    memset(f, 0, sizeof(*f));
    f->hdr.magic = buf[0];
    f->hdr.version = buf[1];
    f->hdr.source_class = buf[2];
    f->hdr.frame_type = buf[3];
    for (i = 0; i < 4; ++i) f->hdr.device_id[i] = (char)buf[4 + i];
    f->hdr.device_id[4] = '\0';
    f->hdr.boot_id = get_u16(buf + 8);
    f->hdr.sequence = get_u32(buf + 10);
    f->hdr.node_time_ms = get_u32(buf + 14);
    dec_payload(buf[3], buf + UMSF_HDR_LEN, f);
    if (umsf_crc16(buf, UMSF_HDR_LEN + pl) != get_u16(buf + UMSF_HDR_LEN + pl)) return UMSF_ERR_CRC;
    return UMSF_OK;
}

void umsf_compact_encode(const umsf_compact_t *c, uint8_t out[UMSF_COMPACT_LEN]) {
    out[0] = UMSF_COMPACT_MAGIC;
    out[1] = c->node_index;
    put_u16(out + 2, c->seq);
    put_u16(out + 4, c->vib_peak_cg);
    put_i16(out + 6, c->tilt_ddeg);
    put_u16(out + 8, c->pressure_dhpa);
    put_i16(out + 10, c->temp);
    put_u16(out + 12, c->gas_mv);
    put_u16(out + 14, c->sound_index);
    out[16] = c->flags;
    out[17] = c->battery_pct;
    put_u16(out + 18, umsf_crc16(out, 18));
}

int umsf_compact_decode(const uint8_t *buf, size_t len, umsf_compact_t *c) {
    if (!buf || !c) return UMSF_ERR_ARG;
    if (len < UMSF_COMPACT_LEN) return UMSF_ERR_SHORT;
    if (len > UMSF_COMPACT_LEN) return UMSF_ERR_LENGTH;
    if (buf[0] != UMSF_COMPACT_MAGIC) return UMSF_ERR_MAGIC;
    c->magic = buf[0];
    c->node_index = buf[1];
    c->seq = get_u16(buf + 2);
    c->vib_peak_cg = get_u16(buf + 4);
    c->tilt_ddeg = get_i16(buf + 6);
    c->pressure_dhpa = get_u16(buf + 8);
    c->temp = get_i16(buf + 10);
    c->gas_mv = get_u16(buf + 12);
    c->sound_index = get_u16(buf + 14);
    c->flags = buf[16];
    c->battery_pct = buf[17];
    return umsf_crc16(buf, 18) == get_u16(buf + 18) ? UMSF_OK : UMSF_ERR_CRC;
}

static const char *const k_event_names[] = {
    NULL, "sos", "sos_reset", "impact_excursion", "loud_sound", "gas_channel_alarm",
    "tilt_change", "pressure_transient", "presence", "link_loss", "possible_impact_local",
    "help_request", "link_restored", "buffer_eviction"};
static const char *const k_event_units[] = {
    NULL, "1", "1", "g", "index", "V", "deg", "Pa", "1/0", "s", "g", "1", "s", "count"};

const char *umsf_event_type_name(uint8_t t) { return t >= 1 && t <= 13 ? k_event_names[t] : NULL; }
const char *umsf_event_unit(uint8_t t) { return t >= 1 && t <= 13 ? k_event_units[t] : NULL; }

const char *umsf_level_name(uint8_t l) {
    static const char *const n[] = {"info", "notice", "warning", "urgent"};
    return l <= 3 ? n[l] : NULL;
}

const char *umsf_source_class_name(uint8_t sc) {
    switch (sc) {
    case UMSF_SRC_PERSONNEL:  return "personnel_node";
    case UMSF_SRC_STATIONARY: return "stationary_node";
    case UMSF_SRC_GATEWAY:    return "gateway";
    default:                  return NULL;
    }
}

const char *umsf_strerror(int code) {
    switch (code) {
    case UMSF_OK:          return "ok";
    case UMSF_ERR_SHORT:   return "short";
    case UMSF_ERR_MAGIC:   return "bad magic";
    case UMSF_ERR_VERSION: return "bad version";
    case UMSF_ERR_TYPE:    return "unknown frame type";
    case UMSF_ERR_LENGTH:  return "bad length";
    case UMSF_ERR_CRC:     return "crc mismatch";
    case UMSF_ERR_ARG:     return "bad argument";
    default:               return "unknown";
    }
}

char *umsf_hex(const uint8_t *buf, size_t len, char *out) {
    static const char d[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < len; ++i) {
        out[2 * i] = d[buf[i] >> 4];
        out[2 * i + 1] = d[buf[i] & 0x0F];
    }
    out[2 * len] = '\0';
    return out;
}
