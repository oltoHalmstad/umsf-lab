// Fragmentation / reassembly tests (spec 2.8).
#include <cstdint>
#include <cstring>

#include "umsf_frag.h"
#include "umsf_proto.h"
#include "umsf_test.h"

namespace {
void fill(uint8_t *b, size_t n, uint8_t seed) { for (size_t i = 0; i < n; ++i) b[i] = (uint8_t)(seed + i * 7); }
}

TEST(frag_single_notification_at_mtu247) {
    uint8_t msg[50], notif[300], out[512];
    fill(msg, sizeof msg, 1);
    CHECK_EQ(umsf_frag_count(50, 244), 1u);  // MTU 247 -> ATT payload 244
    size_t n = umsf_frag_build(msg, 50, 0x1234, 0, 244, notif, sizeof notif);
    CHECK_EQ(n, 54u);
    CHECK_EQ(notif[0], 0x34); CHECK_EQ(notif[1], 0x12); CHECK_EQ(notif[2], 0); CHECK_EQ(notif[3], 1);
    umsf_reasm_t r;
    umsf_reasm_init(&r);
    size_t ol = 0;
    CHECK_EQ(umsf_reasm_push(&r, notif, n, 0, out, sizeof out, &ol), UMSF_REASM_COMPLETE);
    CHECK_EQ(ol, 50u);
    CHECK(std::memcmp(out, msg, 50) == 0);
}

TEST(frag_default_mtu_out_of_order) {
    uint8_t msg[52], notif[4][32], out[512];
    size_t len[4];
    fill(msg, sizeof msg, 9);
    unsigned cnt = umsf_frag_count(52, 20);  // MTU 23 -> 16-byte chunks
    CHECK_EQ(cnt, 4u);
    for (unsigned i = 0; i < cnt; ++i) len[i] = umsf_frag_build(msg, 52, 7, i, 20, notif[i], sizeof notif[i]);
    CHECK_EQ(len[3], 4u + 4u);
    umsf_reasm_t r;
    umsf_reasm_init(&r);
    size_t ol = 0;
    CHECK_EQ(umsf_reasm_push(&r, notif[3], len[3], 0, out, sizeof out, &ol), UMSF_REASM_INCOMPLETE);
    CHECK_EQ(umsf_reasm_push(&r, notif[1], len[1], 5, out, sizeof out, &ol), UMSF_REASM_INCOMPLETE);
    CHECK_EQ(umsf_reasm_push(&r, notif[1], len[1], 6, out, sizeof out, &ol), UMSF_REASM_DUPLICATE);
    CHECK_EQ(umsf_reasm_push(&r, notif[0], len[0], 7, out, sizeof out, &ol), UMSF_REASM_INCOMPLETE);
    CHECK_EQ(umsf_reasm_push(&r, notif[2], len[2], 8, out, sizeof out, &ol), UMSF_REASM_COMPLETE);
    CHECK_EQ(ol, 52u);
    CHECK(std::memcmp(out, msg, 52) == 0);
    CHECK_EQ(r.completed, 1u);
    CHECK_EQ(r.duplicates, 1u);
}

TEST(frag_timeout_2s) {
    uint8_t msg[52], a[32], b[32], out[512];
    fill(msg, sizeof msg, 3);
    size_t la = umsf_frag_build(msg, 52, 1, 0, 20, a, sizeof a);
    size_t lb = umsf_frag_build(msg, 52, 1, 1, 20, b, sizeof b);
    umsf_reasm_t r;
    umsf_reasm_init(&r);
    size_t ol;
    CHECK_EQ(umsf_reasm_push(&r, a, la, 1000, out, sizeof out, &ol), UMSF_REASM_INCOMPLETE);
    CHECK_EQ(umsf_reasm_expire(&r, 3000), 0u);   // exactly 2 s: still alive
    CHECK_EQ(umsf_reasm_expire(&r, 3001), 1u);   // > 2 s: dropped
    CHECK_EQ(r.timed_out, 1u);
    // late fragment starts a new (incomplete) message, never completes the expired one
    CHECK_EQ(umsf_reasm_push(&r, b, lb, 3002, out, sizeof out, &ol), UMSF_REASM_INCOMPLETE);
    CHECK_EQ(r.completed, 0u);
}

TEST(frag_512_limit) {
    static uint8_t big[800], notif[300], out[800];
    fill(big, sizeof big, 5);
    CHECK_EQ(umsf_frag_count(512, 244), 3u);
    CHECK_EQ(umsf_frag_count(513, 244), 0u);  // sender refuses > 512 B
    // a malicious/buggy sender declaring 3 fragments of 240 B overflows the 512 B limit
    umsf_reasm_t r;
    umsf_reasm_init(&r);
    size_t ol;
    for (int i = 0; i < 3; ++i) {
        notif[0] = 9; notif[1] = 0; notif[2] = (uint8_t)i; notif[3] = 3;
        std::memcpy(notif + 4, big + i * 240, 240);
        int res = umsf_reasm_push(&r, notif, 244, 10, out, sizeof out, &ol);
        if (i < 2) CHECK_EQ(res, UMSF_REASM_INCOMPLETE);
        else CHECK_EQ(res, UMSF_REASM_E_OVERFLOW);
    }
    CHECK_EQ(r.overflowed, 1u);
    // exactly 512 B assembles fine
    for (unsigned i = 0; i < 3; ++i) {
        size_t n = umsf_frag_build(big, 512, 10, i, 244, notif, sizeof notif);
        int res = umsf_reasm_push(&r, notif, n, 20, out, sizeof out, &ol);
        CHECK_EQ(res, i < 2 ? UMSF_REASM_INCOMPLETE : UMSF_REASM_COMPLETE);
    }
    CHECK_EQ(ol, 512u);
    CHECK(std::memcmp(out, big, 512) == 0);
}

TEST(frag_three_concurrent_and_eviction) {
    uint8_t m[4][52], out[512];
    size_t ol;
    umsf_reasm_t r;
    umsf_reasm_init(&r);
    for (int k = 0; k < 4; ++k) fill(m[k], 52, (uint8_t)(k * 31));
    // ATT payload 36 -> 32-byte chunks -> 2 fragments per 52 B frame
    uint8_t a[4][40], b[4][40];
    size_t la[4], lb[4];
    for (int k = 0; k < 4; ++k) {
        la[k] = umsf_frag_build(m[k], 52, (uint16_t)(100 + k), 0, 36, a[k], sizeof a[k]);
        lb[k] = umsf_frag_build(m[k], 52, (uint16_t)(100 + k), 1, 36, b[k], sizeof b[k]);
    }
    // three interleaved messages complete independently
    for (int k = 0; k < 3; ++k) CHECK_EQ(umsf_reasm_push(&r, a[k], la[k], (uint32_t)k, out, sizeof out, &ol), UMSF_REASM_INCOMPLETE);
    for (int k = 2; k >= 0; --k) {
        CHECK_EQ(umsf_reasm_push(&r, b[k], lb[k], 10, out, sizeof out, &ol), UMSF_REASM_COMPLETE);
        CHECK(std::memcmp(out, m[k], 52) == 0);
    }
    // a fourth concurrent message evicts the oldest incomplete one
    for (int k = 0; k < 4; ++k) umsf_reasm_push(&r, a[k], la[k], (uint32_t)(20 + k), out, sizeof out, &ol);
    CHECK_EQ(r.slot_evicted, 1u);
    CHECK_EQ(umsf_reasm_push(&r, b[0], lb[0], 30, out, sizeof out, &ol), UMSF_REASM_INCOMPLETE);  // msg 100 was evicted
    CHECK_EQ(umsf_reasm_push(&r, b[3], lb[3], 30, out, sizeof out, &ol), UMSF_REASM_COMPLETE);
}

TEST(frag_malformed) {
    uint8_t n1[5] = {1, 0, 2, 2, 0xAA};  // index >= count
    uint8_t n2[4] = {1, 0, 0, 1};        // header only
    uint8_t out[64];
    size_t ol;
    umsf_reasm_t r;
    umsf_reasm_init(&r);
    CHECK_EQ(umsf_reasm_push(&r, n1, 5, 0, out, sizeof out, &ol), UMSF_REASM_E_MALFORMED);
    CHECK_EQ(umsf_reasm_push(&r, n2, 4, 0, out, sizeof out, &ol), UMSF_REASM_E_MALFORMED);
    CHECK_EQ(r.malformed, 2u);
}
