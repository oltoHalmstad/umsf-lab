/*
 * umsf_json.h - JSON records published by the gateway over MQTT (spec 4, 5).
 *
 * All scaled values are printed from integers (no float rounding). Null sentinels -> JSON null.
 *
 * Time handling (implementation choice, documented in docs/ARCHITECTURE.md):
 *  - The gateway keeps an uptime-based local clock and learns a UTC offset from SNTP.
 *  - Node time (uptime ms) is mapped per node with umsf_timemap_t: offset = rx_local - node_ms,
 *    the minimum over live first transmissions is used (transit latency >= 0), and the stated
 *    uncertainty = observed offset spread + latency allowance + drift allowance + SNTP uncertainty.
 *  - If the gateway clock is not SNTP-synchronised, measured_at / received_at / observed_at /
 *    reported_at and time_uncertainty_s are JSON null; node_time_ms is still recoverable from
 *    frame_hex. In practice the gateway also cannot validate broker certificates without a
 *    valid clock, so records stay buffered until SNTP sync.
 */
#ifndef UMSF_JSON_H
#define UMSF_JSON_H

#include "umsf_proto.h"

#ifdef __cplusplus
extern "C" {
#endif

#define UMSF_TIME_UNKNOWN (-1LL)

typedef struct {
    const char *data_origin;       /* synthetic | synthetic_payload_physical_transport | bench_transcription | measured */
    const char *scenario_id;       /* NULL -> null */
    const char *site_id;
    const char *gateway_id;
    const char *zone_id;           /* NULL -> null (station/event) or omitted (physio) */
    const char *worker_pseudonym;  /* physio only, NULL -> omitted */
    const char *subject_device_id; /* event only: node concerned by a gateway-generated event */
    const char *method;            /* event provenance.method, NULL -> default */
    int64_t measured_at_ms;        /* UTC epoch ms or UMSF_TIME_UNKNOWN */
    int64_t received_at_ms;        /* UTC epoch ms or UMSF_TIME_UNKNOWN */
    int32_t time_uncertainty_ms;   /* < 0 -> null */
    int attachment_verified;       /* station: commissioning recorded verified mounting + baseline */
} umsf_json_ctx_t;

void umsf_json_ctx_init(umsf_json_ctx_t *c);

/* Each returns characters written (excluding NUL) or -1 on overflow / wrong frame type.
 * raw/raw_len is the original frame (for frame_hex); may be NULL to omit frame_hex. */
int umsf_json_physio(const umsf_json_ctx_t *c, const umsf_frame_t *f, const uint8_t *raw, size_t raw_len, char *out, size_t cap);
int umsf_json_station(const umsf_json_ctx_t *c, const umsf_frame_t *f, const uint8_t *raw, size_t raw_len, char *out, size_t cap);
int umsf_json_event(const umsf_json_ctx_t *c, const umsf_frame_t *f, const uint8_t *raw, size_t raw_len, char *out, size_t cap);
int umsf_json_node_status(const umsf_json_ctx_t *c, const umsf_frame_t *f, char *out, size_t cap);
/* Dispatch on frame type (physio/station/event). */
int umsf_json_record(const umsf_json_ctx_t *c, const umsf_frame_t *f, const uint8_t *raw, size_t raw_len, char *out, size_t cap);

/* "YYYY-MM-DDTHH:MM:SS.mmmZ" (needs 25 bytes). Returns out, or NULL for negative input. */
char *umsf_iso8601_ms(int64_t epoch_ms, char *out, size_t cap);

/* ---- node-time to gateway-local mapping ---- */
typedef struct {
    int      valid;
    uint16_t boot_id;
    uint32_t last_seq;        /* highest sequence seen in this boot (live detection) */
    int64_t  min_off, max_off;/* current estimate window */
    int64_t  win_start_local;
    int64_t  next_min, next_max;
    uint32_t next_n;
    uint32_t latency_allowance_ms; /* default 250 */
    uint32_t drift_ppm;            /* default 100 (two 50 ppm crystals) */
    uint32_t window_ms;            /* re-anchoring window, default 600000 */
} umsf_timemap_t;

void umsf_timemap_init(umsf_timemap_t *t);
/* Observe a received frame. Only first transmissions (sequence above the highest seen in the
 * boot session) update the estimate; resends after reconnect would bias it. */
void umsf_timemap_observe(umsf_timemap_t *t, uint16_t boot_id, uint32_t seq, uint32_t node_ms, int64_t rx_local_ms);
/* Map node_ms to gateway-local ms. Returns 0 on success, -1 if no mapping for that boot. */
int umsf_timemap_map(const umsf_timemap_t *t, uint16_t boot_id, uint32_t node_ms, int64_t now_local_ms,
                     int64_t *local_ms, uint32_t *uncertainty_ms);

#ifdef __cplusplus
}
#endif
#endif
