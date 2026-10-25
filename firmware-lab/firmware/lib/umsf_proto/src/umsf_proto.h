/*
 * umsf_proto.h - UMSF shared protocol v1.0 frame codec (portable C99).
 *
 * Implements spec/PROTOCOL.md sections 2.1-2.7 and 2.9: common 18-byte header,
 * fixed-length payloads, CRC-16/CCITT-FALSE trailer, null sentinels and the
 * 20-byte COMPACT stationary packet. All multi-byte fields are little-endian.
 * The CRC detects corruption only; it is not authentication.
 */
#ifndef UMSF_PROTO_H
#define UMSF_PROTO_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define UMSF_MAGIC          0xB5u
#define UMSF_VERSION        1u
#define UMSF_COMPACT_MAGIC  0xC5u

#define UMSF_HDR_LEN        18u
#define UMSF_CRC_LEN        2u
#define UMSF_COMPACT_LEN    20u
#define UMSF_MAX_FRAME_LEN  (UMSF_HDR_LEN + 32u + UMSF_CRC_LEN) /* largest: STATION_STATE */

/* Null sentinels (spec 2.1): a missing measurement is never zero/normal. */
#define UMSF_NULL_U8   ((uint8_t)0xFFu)
#define UMSF_NULL_U16  ((uint16_t)0xFFFFu)
#define UMSF_NULL_I16  ((int16_t)-32768)
#define UMSF_NULL_U32  ((uint32_t)0xFFFFFFFFu)
#define UMSF_NULL_I32  ((int32_t)INT32_MIN)

typedef enum {
    UMSF_SRC_PERSONNEL  = 1,
    UMSF_SRC_STATIONARY = 2,
    UMSF_SRC_GATEWAY    = 3
} umsf_source_class_t;

typedef enum {
    UMSF_FT_PHYSIO_FEATURE = 1,
    UMSF_FT_STATION_STATE  = 2,
    UMSF_FT_EVENT          = 3,
    UMSF_FT_STATUS         = 4,
    UMSF_FT_ACK            = 5,
    UMSF_FT_CONFIG         = 6
} umsf_frame_type_t;

#define UMSF_PL_PHYSIO   30u
#define UMSF_PL_STATION  32u
#define UMSF_PL_EVENT    12u
#define UMSF_PL_STATUS   16u
#define UMSF_PL_ACK       8u
#define UMSF_PL_CONFIG    8u

/* PHYSIO_FEATURE channel_flags */
#define UMSF_CH_T              0x01u
#define UMSF_CH_PPG            0x02u
#define UMSF_CH_MOTION         0x04u
#define UMSF_CH_HR_SYNTHETIC   0x08u
#define UMSF_CH_GSR            0x10u
#define UMSF_CH_SOS_ACTIVE     0x20u
#define UMSF_CH_SPO2_VALIDATED 0x40u

/* PHYSIO_FEATURE artifact_flags */
#define UMSF_AF_MOTION_ARTIFACT 0x01u
#define UMSF_AF_NO_CONTACT      0x02u
#define UMSF_AF_SATURATION      0x04u
#define UMSF_AF_SAMPLE_GAP      0x08u
#define UMSF_AF_TEMP_ERROR      0x10u
#define UMSF_AF_IMU_ERROR       0x20u

/* STATION_STATE.flags (also COMPACT.flags) */
#define UMSF_SF_PIR_PRESENCE        0x01u
#define UMSF_SF_SOS_ACTIVE          0x02u
#define UMSF_SF_IMPACT              0x04u
#define UMSF_SF_LOUD_SOUND          0x08u
#define UMSF_SF_GAS_ALARM           0x10u
#define UMSF_SF_TILT_ALARM          0x20u
#define UMSF_SF_PRESSURE_TRANSIENT  0x40u
#define UMSF_SF_ATTACHMENT_UNCERTAIN 0x80u

/* STATION_STATE.sensor_flags */
#define UMSF_SEN_IMU_OK   0x01u
#define UMSF_SEN_BMP_OK   0x02u
#define UMSF_SEN_GAS_WARM 0x04u
#define UMSF_SEN_MIC_OK   0x08u
#define UMSF_SEN_PIR_OK   0x10u

typedef enum {
    UMSF_EV_SOS                   = 1,
    UMSF_EV_SOS_RESET             = 2,
    UMSF_EV_IMPACT_EXCURSION      = 3,
    UMSF_EV_LOUD_SOUND            = 4,
    UMSF_EV_GAS_CHANNEL_ALARM     = 5,
    UMSF_EV_TILT_CHANGE           = 6,
    UMSF_EV_PRESSURE_TRANSIENT    = 7,
    UMSF_EV_PRESENCE              = 8,
    UMSF_EV_LINK_LOSS             = 9,
    UMSF_EV_POSSIBLE_IMPACT_LOCAL = 10,
    UMSF_EV_HELP_REQUEST          = 11,
    UMSF_EV_LINK_RESTORED         = 12,
    UMSF_EV_BUFFER_EVICTION       = 13
} umsf_event_type_t;

typedef enum { UMSF_LVL_INFO = 0, UMSF_LVL_NOTICE = 1, UMSF_LVL_WARNING = 2, UMSF_LVL_URGENT = 3 } umsf_level_t;

typedef struct {
    uint8_t  magic;
    uint8_t  version;
    uint8_t  source_class;
    uint8_t  frame_type;
    char     device_id[5];   /* 4 ASCII bytes on the wire + local NUL terminator */
    uint16_t boot_id;
    uint32_t sequence;
    uint32_t node_time_ms;
} umsf_header_t;

typedef struct {
    int16_t  skin_temp;          /* degC x100 */
    uint16_t hr;                 /* bpm x10 */
    uint16_t spo2;               /* % x10, null by default */
    uint32_t ppg_ir_mean;
    uint16_t ppg_red_mean_div16;
    uint16_t ppg_valid_permille;
    uint16_t motion_rms_mg;
    uint16_t gsr_mv;
    uint8_t  quality_pct;
    uint8_t  battery_pct;
    uint8_t  channel_flags;
    uint8_t  artifact_flags;
    uint16_t n_ppg_samples;
    uint16_t n_imu_samples;
    uint16_t window_ms;
    uint16_t fw_build;
} umsf_physio_t;

typedef struct {
    uint16_t vib_peak_cg;
    uint16_t accel_rms_mg;
    int16_t  tilt_ddeg;
    int16_t  tilt_delta_ddeg;
    uint16_t pressure_dhpa;
    int16_t  pressure_delta_pa;
    int16_t  temp;
    uint16_t gas_mv;
    uint16_t gas_baseline_mv;
    uint16_t sound_index;
    uint8_t  flags;
    uint8_t  quality_pct;
    uint8_t  battery_pct;
    uint8_t  sensor_flags;
    uint16_t n_imu_samples;
    uint16_t window_ms;
    uint16_t zone_code;
    uint16_t fw_build;
} umsf_station_t;

typedef struct {
    uint8_t  event_type;
    uint8_t  level;
    int32_t  value;           /* x1000 */
    uint16_t rule_version;
    uint16_t zone_code;
    uint16_t related_seq_lo;
} umsf_event_t;

typedef struct {
    uint8_t  battery_pct;
    uint8_t  buffered_records;
    uint16_t evicted_total;
    uint32_t sent_total;
    uint32_t acked_up_to_seq;
    uint16_t fw_build;
    uint8_t  sensor_flags;
    uint8_t  rssi_neg;
} umsf_status_t;

typedef struct {
    uint16_t target_boot_id;
    uint16_t reserved;
    uint32_t ack_up_to_seq;
} umsf_ack_t;

typedef struct {
    uint16_t zone_code;
    uint16_t feature_window_ms;
    uint8_t  sample_profile;
    uint8_t  synthetic_hr_enabled;
    uint16_t reserved;
} umsf_config_t;

typedef struct {
    umsf_header_t hdr;
    union {
        umsf_physio_t  physio;
        umsf_station_t station;
        umsf_event_t   event;
        umsf_status_t  status;
        umsf_ack_t     ack;
        umsf_config_t  config;
    } u;
} umsf_frame_t;

typedef struct {
    uint8_t  magic;
    uint8_t  node_index;
    uint16_t seq;
    uint16_t vib_peak_cg;
    int16_t  tilt_ddeg;
    uint16_t pressure_dhpa;
    int16_t  temp;
    uint16_t gas_mv;
    uint16_t sound_index;
    uint8_t  flags;
    uint8_t  battery_pct;
} umsf_compact_t;

typedef enum {
    UMSF_OK = 0,
    UMSF_ERR_SHORT = -1,     /* fewer bytes than header or than declared type needs */
    UMSF_ERR_MAGIC = -2,
    UMSF_ERR_VERSION = -3,
    UMSF_ERR_TYPE = -4,
    UMSF_ERR_LENGTH = -5,    /* trailing bytes beyond the fixed frame length */
    UMSF_ERR_CRC = -6,       /* fields decoded, but CRC mismatch: frame must be rejected */
    UMSF_ERR_ARG = -7
} umsf_status_code_t;

/* CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, xorout 0. */
uint16_t umsf_crc16(const uint8_t *data, size_t len);
uint16_t umsf_crc16_update(uint16_t crc, const uint8_t *data, size_t len);

/* Payload length for a frame type, 0 if unknown. */
size_t umsf_payload_len(uint8_t frame_type);
/* Total serialized frame length (header + payload + CRC), 0 if unknown. */
size_t umsf_frame_len(uint8_t frame_type);

/* Fill a header with magic/version and copy up to 4 chars of device_id. */
void umsf_header_init(umsf_header_t *h, uint8_t source_class, uint8_t frame_type,
                      const char *device_id, uint16_t boot_id, uint32_t sequence,
                      uint32_t node_time_ms);

/* Initialise payloads with all measurement fields set to their null sentinel. */
void umsf_physio_set_null(umsf_physio_t *p);
void umsf_station_set_null(umsf_station_t *s);
void umsf_status_set_null(umsf_status_t *s);

/* Encode frame into out. Returns bytes written or 0 on error (unknown type / small buffer). */
size_t umsf_encode(const umsf_frame_t *f, uint8_t *out, size_t cap);

/* Decode a complete frame. Returns UMSF_OK or a negative umsf_status_code_t.
 * On UMSF_ERR_CRC the fields are still filled (for diagnostics only). */
int umsf_decode(const uint8_t *buf, size_t len, umsf_frame_t *f);

/* COMPACT 20-byte packet (no fragment header). */
void umsf_compact_encode(const umsf_compact_t *c, uint8_t out[UMSF_COMPACT_LEN]);
int  umsf_compact_decode(const uint8_t *buf, size_t len, umsf_compact_t *c);

const char *umsf_event_type_name(uint8_t event_type);   /* "sos", ..., NULL if unknown */
const char *umsf_event_unit(uint8_t event_type);        /* unit column of spec 2.4 */
const char *umsf_level_name(uint8_t level);             /* info/notice/warning/urgent */
const char *umsf_source_class_name(uint8_t source_class);
const char *umsf_strerror(int code);

/* Lowercase hex of buf into out (needs 2*len+1). Returns out. */
char *umsf_hex(const uint8_t *buf, size_t len, char *out);

#ifdef __cplusplus
}
#endif
#endif /* UMSF_PROTO_H */
