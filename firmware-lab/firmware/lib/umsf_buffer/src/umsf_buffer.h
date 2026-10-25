/*
 * umsf_buffer.h - RAM buffer of unacknowledged records (spec 6; paper 3.3.7, A.2).
 *
 * - Node: >= 30 unacked feature records (5 min at 10 s). Gateway: >= 18 (60 s across 3 nodes).
 * - Records are released only by a cumulative *application* ACK (source, boot_id, ack_up_to_seq)
 *   issued after the site agent's durable COMMIT. An MQTT QoS 1 PUBACK never releases a record.
 * - When full, the oldest record of the lowest priority present is evicted (telemetry before
 *   events, so a latched SOS/help request is the last thing to go); evictions are counted and reported once via
 *   take_eviction_report() so the firmware can emit an explicit buffer_eviction EVENT.
 * - RAM only: contents do NOT survive reset or power loss (the paper states this limitation).
 *
 * Ordering: next_to_send() returns the oldest unsent record of the highest priority
 * (EVENT frames before telemetry), giving one ordered uplink stream per buffer.
 * Portable C++17, no heap, no exceptions.
 */
#ifndef UMSF_BUFFER_H
#define UMSF_BUFFER_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace umsf {

enum Priority : uint8_t { PRIO_TELEMETRY = 0, PRIO_EVENT = 1, PRIO_URGENT = 2 };

template <size_t N, size_t MAXLEN>
class RecordBuffer {
public:
    static_assert(N >= 1 && N <= 255, "capacity must fit STATUS.buffered_records (u8)");

    struct Entry {
        bool used;
        bool sent;
        uint8_t src;        // source index (node slot at the gateway; 0 on a node)
        uint8_t prio;
        uint16_t boot_id;
        uint32_t seq;
        uint32_t order;     // insertion order (eviction = smallest)
        uint32_t t_in_ms;   // time inserted (local)
        uint32_t t_sent_ms; // last transmission time
        uint16_t len;
        uint8_t data[MAXLEN];
    };

    enum PushResult { PUSH_OK = 0, PUSH_EVICTED = 1, PUSH_DUPLICATE = 2, PUSH_TOO_LONG = -1 };

    RecordBuffer() { clear(); }

    void clear() {
        memset(e_, 0, sizeof(e_));
        count_ = 0;
        next_order_ = 0;
        pending_evictions_ = 0;
    }

    // Insert a record. Identical identity (src, boot, seq) already held -> DUPLICATE (idempotent).
    PushResult push(uint8_t src, uint16_t boot_id, uint32_t seq, uint8_t prio,
                    const uint8_t *data, size_t len, uint32_t now_ms) {
        if (len > MAXLEN) return PUSH_TOO_LONG;
        if (find(src, boot_id, seq) >= 0) return PUSH_DUPLICATE;
        PushResult r = PUSH_OK;
        int slot = free_slot();
        if (slot < 0) {
            slot = victim();
            ++evicted_total_;
            ++pending_evictions_;
            last_evicted_seq_ = e_[slot].seq;
            --count_;
            r = PUSH_EVICTED;
        }
        Entry &x = e_[slot];
        x.used = true;
        x.sent = false;
        x.src = src;
        x.prio = prio;
        x.boot_id = boot_id;
        x.seq = seq;
        x.order = next_order_++;
        x.t_in_ms = now_ms;
        x.t_sent_ms = 0;
        x.len = static_cast<uint16_t>(len);
        memcpy(x.data, data, len);
        ++count_;
        return r;
    }

    // Cumulative application ack: release every record of (src, boot_id) with seq <= up_to.
    size_t ack(uint8_t src, uint16_t boot_id, uint32_t up_to) {
        size_t n = 0;
        for (auto &x : e_) {
            if (x.used && x.src == src && x.boot_id == boot_id && x.seq <= up_to) {
                x.used = false;
                --count_;
                ++n;
            }
        }
        acked_total_ += n;
        return n;
    }

    // Highest priority, oldest unsent record; nullptr if none.
    Entry *next_to_send() {
        Entry *best = nullptr;
        for (auto &x : e_) {
            if (!x.used || x.sent) continue;
            if (!best || x.prio > best->prio || (x.prio == best->prio && before(x.order, best->order))) best = &x;
        }
        return best;
    }
    // Like next_to_send() but restricted to one source.
    Entry *next_to_send(uint8_t src) {
        Entry *best = nullptr;
        for (auto &x : e_) {
            if (!x.used || x.sent || x.src != src) continue;
            if (!best || x.prio > best->prio || (x.prio == best->prio && before(x.order, best->order))) best = &x;
        }
        return best;
    }

    void mark_sent(Entry *x, uint32_t now_ms) {
        if (!x) return;
        x->sent = true;
        x->t_sent_ms = now_ms;
        ++sent_total_;
    }

    // After reconnect: every unacked record of src (or all if src < 0) becomes eligible again.
    void reset_sent(int src = -1) {
        for (auto &x : e_)
            if (x.used && (src < 0 || x.src == src)) x.sent = false;
    }

    // Retransmit records sent more than timeout_ms ago without an application ack.
    size_t requeue_stale(uint32_t now_ms, uint32_t timeout_ms) {
        size_t n = 0;
        for (auto &x : e_)
            if (x.used && x.sent && (uint32_t)(now_ms - x.t_sent_ms) >= timeout_ms) { x.sent = false; ++n; }
        return n;
    }

    // Number of evictions since the last call (for an explicit buffer_eviction event).
    uint32_t take_eviction_report() { uint32_t n = pending_evictions_; pending_evictions_ = 0; return n; }

    size_t size() const { return count_; }
    static constexpr size_t capacity() { return N; }
    bool empty() const { return count_ == 0; }
    uint32_t evicted_total() const { return evicted_total_; }
    uint32_t sent_total() const { return sent_total_; }
    uint32_t acked_total() const { return acked_total_; }
    uint32_t last_evicted_seq() const { return last_evicted_seq_; }

    bool contains(uint8_t src, uint16_t boot_id, uint32_t seq) const { return find(src, boot_id, seq) >= 0; }

    template <typename F> void for_each(F f) const {
        for (const auto &x : e_) if (x.used) f(x);
    }

private:
    static bool before(uint32_t a, uint32_t b) { return (int32_t)(a - b) < 0; }
    int find(uint8_t src, uint16_t boot, uint32_t seq) const {
        for (size_t i = 0; i < N; ++i)
            if (e_[i].used && e_[i].src == src && e_[i].boot_id == boot && e_[i].seq == seq) return (int)i;
        return -1;
    }
    int free_slot() const {
        for (size_t i = 0; i < N; ++i) if (!e_[i].used) return (int)i;
        return -1;
    }
    int victim() const {  // lowest priority first, then oldest
        int o = -1;
        for (size_t i = 0; i < N; ++i) {
            if (!e_[i].used) continue;
            if (o < 0 || e_[i].prio < e_[o].prio || (e_[i].prio == e_[o].prio && before(e_[i].order, e_[o].order)))
                o = (int)i;
        }
        return o;
    }

    Entry e_[N];
    size_t count_ = 0;
    uint32_t next_order_ = 0;
    uint32_t evicted_total_ = 0;
    uint32_t pending_evictions_ = 0;
    uint32_t last_evicted_seq_ = 0;
    uint32_t sent_total_ = 0;
    uint32_t acked_total_ = 0;
};

// Default capacities used by the firmware (both above the paper minimums).
constexpr size_t kNodeBufferRecords = 32;     // >= 30 (5 min of 10 s feature records)
constexpr size_t kGatewayBufferRecords = 48;  // >= 18 (60 s across 3 personnel nodes)

}  // namespace umsf
#endif
