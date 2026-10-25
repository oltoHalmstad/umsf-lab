/*
 * umsf_gwcore.h - portable gateway logic (C++17): node link supervision, site-agent ACK
 * parsing and enrollment allowlist lookup. Hardware-free so it is host-tested.
 *
 * Link semantics (protocol 0.7): silence makes current evidence `unknown`. The gateway emits
 * link_loss (value = s since last frame) and link_restored (value = outage s); it never
 * infers collapse or casualty from a lost link.
 */
#ifndef UMSF_GWCORE_H
#define UMSF_GWCORE_H

#include <ctype.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "umsf_proto.h"

namespace umsf {

struct LinkEvent {
    uint8_t node;        // gateway slot index
    uint8_t type;        // UMSF_EV_LINK_LOSS or UMSF_EV_LINK_RESTORED
    int32_t value_x1000; // seconds x1000
};

template <size_t N>
class LinkMonitor {
public:
    enum State : uint8_t { UNKNOWN = 0, UP, LOST };

    // stale_ms: 2000 for stationary nodes (COMPACT every 200 ms, paper 3.4.4);
    // for personnel nodes 25000 (2.5 x 10 s feature interval) is the implementation default.
    void configure(size_t i, uint32_t stale_ms) { if (i < N) n_[i] = Node{true, stale_ms, UNKNOWN, 0, 0}; }

    bool on_frame(size_t i, uint32_t now, LinkEvent &ev) {
        if (i >= N || !n_[i].enrolled) return false;
        Node &x = n_[i];
        bool restored = x.state == LOST;
        if (restored) ev = LinkEvent{(uint8_t)i, UMSF_EV_LINK_RESTORED, (int32_t)(now - x.last_rx)};
        x.state = UP;
        x.last_rx = now;
        return restored;
    }

    // BLE disconnect: immediate loss if the link was up.
    bool on_disconnect(size_t i, uint32_t now, LinkEvent &ev) {
        if (i >= N || n_[i].state != UP) return false;
        return lose(i, now, ev);
    }

    // Staleness supervision. Returns number of loss events written to out.
    size_t tick(uint32_t now, LinkEvent *out, size_t max) {
        size_t k = 0;
        for (size_t i = 0; i < N && k < max; ++i)
            if (n_[i].enrolled && n_[i].state == UP && (uint32_t)(now - n_[i].last_rx) > n_[i].stale_ms)
                if (lose(i, now, out[k])) ++k;
        return k;
    }

    State state(size_t i) const { return i < N ? n_[i].state : UNKNOWN; }
    bool fresh(size_t i, uint32_t now) const {
        return i < N && n_[i].state == UP && (uint32_t)(now - n_[i].last_rx) <= n_[i].stale_ms;
    }
    // ms since last frame, or UINT32_MAX if never received
    uint32_t age_ms(size_t i, uint32_t now) const {
        return i < N && n_[i].state != UNKNOWN ? now - n_[i].last_rx : UINT32_MAX;
    }

private:
    struct Node { bool enrolled; uint32_t stale_ms; State state; uint32_t last_rx; uint32_t lost_at; };
    bool lose(size_t i, uint32_t now, LinkEvent &ev) {
        Node &x = n_[i];
        x.state = LOST;
        x.lost_at = now;
        ev = LinkEvent{(uint8_t)i, UMSF_EV_LINK_LOSS, (int32_t)(now - x.last_rx)};
        return true;
    }
    Node n_[N] = {};
};

// ---- site agent -> gateway application ACK: {"device_id","boot_id","ack_up_to_seq"} ----
struct SiteAck {
    char device_id[5];
    uint16_t boot_id;
    uint32_t ack_up_to_seq;
};

namespace detail {
// Find "key" at object level and return pointer to the first char of its value (after ':').
inline const char *json_value(const char *s, size_t len, const char *key) {
    size_t kl = strlen(key);
    for (size_t i = 0; i + kl + 2 <= len; ++i) {
        if (s[i] == '"' && strncmp(s + i + 1, key, kl) == 0 && s[i + 1 + kl] == '"') {
            size_t j = i + kl + 2;
            while (j < len && isspace((unsigned char)s[j])) ++j;
            if (j < len && s[j] == ':') {
                ++j;
                while (j < len && isspace((unsigned char)s[j])) ++j;
                return j < len ? s + j : nullptr;
            }
        }
    }
    return nullptr;
}
inline bool json_uint(const char *s, size_t len, const char *key, uint32_t max, uint32_t &out) {
    const char *v = json_value(s, len, key);
    if (!v || !isdigit((unsigned char)*v)) return false;
    unsigned long long x = 0;
    const char *end = s + len;
    while (v < end && isdigit((unsigned char)*v)) {
        x = x * 10 + (unsigned)(*v++ - '0');
        if (x > max) return false;
    }
    out = (uint32_t)x;
    return true;
}
}  // namespace detail

// Returns true only if all three keys are present and in range; device_id must be 1..4 ASCII chars.
inline bool parse_site_ack(const char *s, size_t len, SiteAck &a) {
    const char *v = detail::json_value(s, len, "device_id");
    if (!v || *v != '"') return false;
    ++v;
    size_t n = 0;
    while (v + n < s + len && v[n] != '"' && n < 5) ++n;
    if (n == 0 || n > 4 || v + n >= s + len || v[n] != '"') return false;
    memset(a.device_id, 0, sizeof a.device_id);
    for (size_t i = 0; i < n; ++i) {
        if ((unsigned char)v[i] < 0x21 || (unsigned char)v[i] > 0x7E) return false;
        a.device_id[i] = v[i];
    }
    uint32_t boot = 0, seq = 0;
    if (!detail::json_uint(s, len, "boot_id", 0xFFFE, boot)) return false;
    if (!detail::json_uint(s, len, "ack_up_to_seq", 0xFFFFFFFEu, seq)) return false;
    a.boot_id = (uint16_t)boot;
    a.ack_up_to_seq = seq;
    return true;
}

// ---- enrollment allowlist ----
struct EnrolledNode {
    const char *device_id;     // "A01"
    const char *ble_addr;      // "aa:bb:cc:dd:ee:ff" (public address)
    uint8_t source_class;      // UMSF_SRC_PERSONNEL / UMSF_SRC_STATIONARY
    uint32_t passkey;          // 6-digit enrollment passkey shown by the node
    uint16_t zone_code;
    const char *zone_id;       // "Z1" etc., used in JSON
    bool attachment_verified;  // stationary: mounting verified at commissioning
};

inline bool addr_equal(const char *a, const char *b) {
    for (; *a && *b; ++a, ++b)
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b)) return false;
    return *a == *b;
}

inline int find_enrolled_by_addr(const EnrolledNode *t, size_t n, const char *addr) {
    for (size_t i = 0; i < n; ++i) if (addr_equal(t[i].ble_addr, addr)) return (int)i;
    return -1;
}
inline int find_enrolled_by_id(const EnrolledNode *t, size_t n, const char *id) {
    for (size_t i = 0; i < n; ++i) if (strncmp(t[i].device_id, id, 4) == 0) return (int)i;
    return -1;
}

}  // namespace umsf
#endif
