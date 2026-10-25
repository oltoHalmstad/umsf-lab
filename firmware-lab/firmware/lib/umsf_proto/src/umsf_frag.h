/*
 * umsf_frag.h - BLE notification fragmentation (spec 2.8).
 *
 * Every TELEMETRY/EVENT notification = 4-byte fragment header
 * (u16 msg_id, u8 frag_index, u8 frag_count) + chunk. frag_count = 1 for a whole frame.
 * Reassembly: 512-byte message limit, 2 s incomplete-message timeout,
 * up to UMSF_REASM_SLOTS concurrent messages per node (one reassembler per node link).
 */
#ifndef UMSF_FRAG_H
#define UMSF_FRAG_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define UMSF_FRAG_HDR_LEN      4u
#define UMSF_REASM_MAX_BYTES   512u
#define UMSF_REASM_TIMEOUT_MS  2000u
#define UMSF_REASM_SLOTS       3u
#define UMSF_REASM_MAX_FRAGS   64u   /* 512 B / 16 B chunks (MTU 23) = 32; 64 leaves margin */

/* Chunk size for a given ATT payload (MTU - 3). 0 if the payload cannot hold a header + 1 byte. */
size_t umsf_frag_chunk_size(size_t att_payload);
/* Number of fragments for msg_len at a given ATT payload; 0 if impossible (too big / too many). */
unsigned umsf_frag_count(size_t msg_len, size_t att_payload);
/* Build notification #index of a message. Returns bytes written to out, 0 on error. */
size_t umsf_frag_build(const uint8_t *msg, size_t msg_len, uint16_t msg_id, unsigned index,
                       size_t att_payload, uint8_t *out, size_t cap);

typedef struct {
    uint8_t  in_use;
    uint16_t msg_id;
    uint8_t  frag_count;
    uint8_t  received;          /* number of distinct fragments stored */
    uint32_t first_ms;
    uint16_t used;              /* bytes stored in data */
    uint64_t mask;              /* received fragment bitmap */
    uint16_t off[UMSF_REASM_MAX_FRAGS];
    uint16_t len[UMSF_REASM_MAX_FRAGS];
    uint8_t  data[UMSF_REASM_MAX_BYTES];
} umsf_reasm_slot_t;

typedef struct {
    umsf_reasm_slot_t slot[UMSF_REASM_SLOTS];
    uint32_t timeout_ms;
    /* diagnostic counters (feed the gateway status record / S6 incomplete-fragment cases) */
    uint32_t completed;
    uint32_t timed_out;
    uint32_t overflowed;
    uint32_t slot_evicted;
    uint32_t malformed;
    uint32_t duplicates;
} umsf_reasm_t;

typedef enum {
    UMSF_REASM_INCOMPLETE = 0,
    UMSF_REASM_COMPLETE   = 1,
    UMSF_REASM_DUPLICATE  = 2,   /* fragment already held: ignored */
    UMSF_REASM_E_MALFORMED = -1, /* bad fragment header */
    UMSF_REASM_E_OVERFLOW  = -2, /* message would exceed 512 B: discarded */
    UMSF_REASM_E_OUTBUF    = -3  /* caller output buffer too small */
} umsf_reasm_result_t;

void umsf_reasm_init(umsf_reasm_t *r);
/* Drop incomplete messages older than timeout. Returns number expired. */
unsigned umsf_reasm_expire(umsf_reasm_t *r, uint32_t now_ms);
/* Push one notification (with fragment header). On COMPLETE, the message is copied into out. */
int umsf_reasm_push(umsf_reasm_t *r, const uint8_t *notif, size_t len, uint32_t now_ms,
                    uint8_t *out, size_t out_cap, size_t *out_len);

#ifdef __cplusplus
}
#endif
#endif
