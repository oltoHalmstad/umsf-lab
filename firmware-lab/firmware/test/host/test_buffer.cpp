// RecordBuffer tests: cumulative ack, eviction, priority ordering, resend.
#include <cstdint>

#include "umsf_buffer.h"
#include "umsf_test.h"

using umsf::RecordBuffer;

TEST(buffer_capacity_minimums) {
    CHECK(umsf::kNodeBufferRecords >= 30);
    CHECK(umsf::kGatewayBufferRecords >= 18);
}

TEST(buffer_cumulative_ack) {
    RecordBuffer<32, 52> b;
    uint8_t d[4] = {1, 2, 3, 4};
    for (uint32_t s = 1; s <= 10; ++s) CHECK_EQ(b.push(0, 1, s, umsf::PRIO_TELEMETRY, d, 4, s * 10), decltype(b)::PUSH_OK);
    CHECK_EQ(b.size(), 10u);
    CHECK_EQ(b.push(0, 1, 5, umsf::PRIO_TELEMETRY, d, 4, 0), decltype(b)::PUSH_DUPLICATE);
    CHECK_EQ(b.ack(0, 2, 10), 0u);  // wrong boot: nothing released
    CHECK_EQ(b.ack(0, 1, 6), 6u);
    CHECK_EQ(b.size(), 4u);
    CHECK(!b.contains(0, 1, 6));
    CHECK(b.contains(0, 1, 7));
    CHECK_EQ(b.ack(0, 1, 6), 0u);   // idempotent
    CHECK_EQ(b.ack(0, 1, 100), 4u);
    CHECK(b.empty());
}

TEST(buffer_oldest_eviction_is_reported) {
    RecordBuffer<30, 52> b;
    uint8_t d[1] = {0};
    for (uint32_t s = 1; s <= 30; ++s) b.push(0, 1, s, 0, d, 1, s);
    CHECK_EQ(b.size(), 30u);
    CHECK_EQ(b.take_eviction_report(), 0u);
    CHECK_EQ(b.push(0, 1, 31, 0, d, 1, 31), decltype(b)::PUSH_EVICTED);
    CHECK_EQ(b.push(0, 1, 32, 0, d, 1, 32), decltype(b)::PUSH_EVICTED);
    CHECK(!b.contains(0, 1, 1));
    CHECK(!b.contains(0, 1, 2));
    CHECK(b.contains(0, 1, 3));
    CHECK_EQ(b.evicted_total(), 2u);
    CHECK_EQ(b.last_evicted_seq(), 2u);
    CHECK_EQ(b.take_eviction_report(), 2u);
    CHECK_EQ(b.take_eviction_report(), 0u);  // reported once
    CHECK_EQ(b.push(0, 1, 33, 0, d, 99, 0), decltype(b)::PUSH_TOO_LONG);
}

TEST(buffer_priority_and_resend) {
    RecordBuffer<8, 52> b;
    uint8_t d[1] = {0};
    b.push(0, 1, 1, umsf::PRIO_TELEMETRY, d, 1, 0);
    b.push(0, 1, 2, umsf::PRIO_TELEMETRY, d, 1, 0);
    b.push(0, 1, 3, umsf::PRIO_URGENT, d, 1, 0);   // SOS / help request
    b.push(0, 1, 4, umsf::PRIO_EVENT, d, 1, 0);
    uint32_t order[4];
    for (int i = 0; i < 4; ++i) {
        auto *e = b.next_to_send();
        CHECK(e != nullptr);
        order[i] = e ? e->seq : 0;
        b.mark_sent(e, 100);
    }
    CHECK_EQ(order[0], 3u); CHECK_EQ(order[1], 4u); CHECK_EQ(order[2], 1u); CHECK_EQ(order[3], 2u);
    CHECK(b.next_to_send() == nullptr);
    CHECK_EQ(b.sent_total(), 4u);
    // no ack within the timeout -> requeued; reconnect -> everything unacked again
    CHECK_EQ(b.requeue_stale(100 + 29999, 30000), 0u);
    CHECK_EQ(b.requeue_stale(100 + 30000, 30000), 4u);
    b.ack(0, 1, 3);
    for (auto *e = b.next_to_send(); e; e = b.next_to_send()) b.mark_sent(e, 200000);
    b.reset_sent();
    auto *e = b.next_to_send();
    CHECK(e && e->seq == 4);
}

TEST(buffer_gateway_multi_source) {
    RecordBuffer<18, 52> g;
    uint8_t d[1] = {0};
    for (uint32_t s = 1; s <= 6; ++s)
        for (uint8_t src = 0; src < 3; ++src) CHECK_EQ(g.push(src, 1, s, 0, d, 1, s), decltype(g)::PUSH_OK);
    CHECK_EQ(g.size(), 18u);  // 60 s across 3 nodes
    CHECK_EQ(g.ack(1, 1, 6), 6u);
    CHECK_EQ(g.size(), 12u);
    auto *e = g.next_to_send(2);
    CHECK(e && e->src == 2 && e->seq == 1);
    g.push(0, 1, 7, 0, d, 1, 7);
    g.reset_sent(0);
    CHECK_EQ(g.evicted_total(), 0u);
}

TEST(buffer_eviction_spares_urgent_events) {
    RecordBuffer<4, 52> b;
    uint8_t d[1] = {0};
    b.push(0, 1, 1, umsf::PRIO_URGENT, d, 1, 0);  // help request, oldest
    b.push(0, 1, 2, umsf::PRIO_TELEMETRY, d, 1, 0);
    b.push(0, 1, 3, umsf::PRIO_EVENT, d, 1, 0);
    b.push(0, 1, 4, umsf::PRIO_TELEMETRY, d, 1, 0);
    b.push(0, 1, 5, umsf::PRIO_TELEMETRY, d, 1, 0);  // evicts seq 2 (oldest telemetry)
    CHECK(b.contains(0, 1, 1));
    CHECK(!b.contains(0, 1, 2));
    b.push(0, 1, 6, umsf::PRIO_TELEMETRY, d, 1, 0);  // evicts seq 4
    b.push(0, 1, 7, umsf::PRIO_TELEMETRY, d, 1, 0);  // evicts seq 5
    b.push(0, 1, 8, umsf::PRIO_TELEMETRY, d, 1, 0);  // evicts seq 6
    CHECK(b.contains(0, 1, 1) && b.contains(0, 1, 3) && b.contains(0, 1, 7) && b.contains(0, 1, 8));
    CHECK_EQ(b.evicted_total(), 4u);
}
