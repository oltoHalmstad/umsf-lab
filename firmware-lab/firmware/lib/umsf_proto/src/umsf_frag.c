/* umsf_frag.c - see umsf_frag.h */
#include "umsf_frag.h"
#include <string.h>

size_t umsf_frag_chunk_size(size_t att_payload) {
    return att_payload > UMSF_FRAG_HDR_LEN ? att_payload - UMSF_FRAG_HDR_LEN : 0;
}

unsigned umsf_frag_count(size_t msg_len, size_t att_payload) {
    size_t chunk = umsf_frag_chunk_size(att_payload), n;
    if (!chunk || msg_len == 0 || msg_len > UMSF_REASM_MAX_BYTES) return 0;
    n = (msg_len + chunk - 1) / chunk;
    return n <= UMSF_REASM_MAX_FRAGS && n <= 255 ? (unsigned)n : 0;
}

size_t umsf_frag_build(const uint8_t *msg, size_t msg_len, uint16_t msg_id, unsigned index,
                       size_t att_payload, uint8_t *out, size_t cap) {
    size_t chunk = umsf_frag_chunk_size(att_payload), off, n;
    unsigned count = umsf_frag_count(msg_len, att_payload);
    if (!count || index >= count) return 0;
    off = (size_t)index * chunk;
    n = msg_len - off < chunk ? msg_len - off : chunk;
    if (cap < UMSF_FRAG_HDR_LEN + n) return 0;
    out[0] = (uint8_t)msg_id;
    out[1] = (uint8_t)(msg_id >> 8);
    out[2] = (uint8_t)index;
    out[3] = (uint8_t)count;
    memcpy(out + UMSF_FRAG_HDR_LEN, msg + off, n);
    return UMSF_FRAG_HDR_LEN + n;
}

void umsf_reasm_init(umsf_reasm_t *r) {
    memset(r, 0, sizeof(*r));
    r->timeout_ms = UMSF_REASM_TIMEOUT_MS;
}

unsigned umsf_reasm_expire(umsf_reasm_t *r, uint32_t now_ms) {
    unsigned i, n = 0;
    for (i = 0; i < UMSF_REASM_SLOTS; ++i) {
        umsf_reasm_slot_t *s = &r->slot[i];
        if (s->in_use && (uint32_t)(now_ms - s->first_ms) > r->timeout_ms) {
            s->in_use = 0;
            ++n;
        }
    }
    r->timed_out += n;
    return n;
}

static umsf_reasm_slot_t *find_or_alloc(umsf_reasm_t *r, uint16_t msg_id, uint32_t now_ms) {
    unsigned i;
    umsf_reasm_slot_t *free_s = NULL, *oldest = NULL;
    for (i = 0; i < UMSF_REASM_SLOTS; ++i) {
        umsf_reasm_slot_t *s = &r->slot[i];
        if (s->in_use && s->msg_id == msg_id) return s;
        if (!s->in_use && !free_s) free_s = s;
        if (s->in_use && (!oldest || (int32_t)(s->first_ms - oldest->first_ms) < 0)) oldest = s;
    }
    if (!free_s) { /* all slots busy: evict the oldest incomplete message */
        free_s = oldest;
        ++r->slot_evicted;
    }
    memset(free_s, 0, offsetof(umsf_reasm_slot_t, off));
    free_s->in_use = 1;
    free_s->msg_id = msg_id;
    free_s->first_ms = now_ms;
    return free_s;
}

int umsf_reasm_push(umsf_reasm_t *r, const uint8_t *notif, size_t len, uint32_t now_ms,
                    uint8_t *out, size_t out_cap, size_t *out_len) {
    uint16_t msg_id;
    uint8_t idx, cnt;
    size_t n = len >= UMSF_FRAG_HDR_LEN ? len - UMSF_FRAG_HDR_LEN : 0;
    umsf_reasm_slot_t *s;
    unsigned i;

    umsf_reasm_expire(r, now_ms);
    if (len <= UMSF_FRAG_HDR_LEN) { ++r->malformed; return UMSF_REASM_E_MALFORMED; }
    msg_id = (uint16_t)(notif[0] | (notif[1] << 8));
    idx = notif[2];
    cnt = notif[3];
    if (cnt == 0 || cnt > UMSF_REASM_MAX_FRAGS || idx >= cnt) { ++r->malformed; return UMSF_REASM_E_MALFORMED; }

    if (cnt == 1) { /* fast path: whole message in one notification */
        if (n > UMSF_REASM_MAX_BYTES) { ++r->overflowed; return UMSF_REASM_E_OVERFLOW; }
        if (out_cap < n) return UMSF_REASM_E_OUTBUF;
        memcpy(out, notif + UMSF_FRAG_HDR_LEN, n);
        *out_len = n;
        ++r->completed;
        return UMSF_REASM_COMPLETE;
    }

    s = find_or_alloc(r, msg_id, now_ms);
    if (s->frag_count == 0) s->frag_count = cnt;
    if (s->frag_count != cnt) { /* inconsistent header for the same msg_id: discard */
        s->in_use = 0;
        ++r->malformed;
        return UMSF_REASM_E_MALFORMED;
    }
    if (s->mask & ((uint64_t)1 << idx)) { ++r->duplicates; return UMSF_REASM_DUPLICATE; }
    if ((size_t)s->used + n > UMSF_REASM_MAX_BYTES) {
        s->in_use = 0;
        ++r->overflowed;
        return UMSF_REASM_E_OVERFLOW;
    }
    memcpy(s->data + s->used, notif + UMSF_FRAG_HDR_LEN, n);
    s->off[idx] = s->used;
    s->len[idx] = (uint16_t)n;
    s->used = (uint16_t)(s->used + n);
    s->mask |= (uint64_t)1 << idx;
    ++s->received;
    if (s->received < s->frag_count) return UMSF_REASM_INCOMPLETE;

    /* complete: concatenate in fragment order */
    s->in_use = 0;
    if (out_cap < s->used) return UMSF_REASM_E_OUTBUF;
    {
        size_t w = 0;
        for (i = 0; i < s->frag_count; ++i) {
            memcpy(out + w, s->data + s->off[i], s->len[i]);
            w += s->len[i];
        }
        *out_len = w;
    }
    ++r->completed;
    return UMSF_REASM_COMPLETE;
}
