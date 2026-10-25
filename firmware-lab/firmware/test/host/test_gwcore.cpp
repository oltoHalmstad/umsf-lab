// Gateway logic tests: link supervision, site ACK parsing, allowlist.
#include <cstring>

#include "umsf_gwcore.h"
#include "umsf_test.h"

using namespace umsf;

TEST(gw_link_loss_and_restore) {
    LinkMonitor<3> m;
    m.configure(0, 2000);   // stationary: COMPACT staleness 2 s
    m.configure(1, 25000);  // personnel
    LinkEvent ev[3] = {};
    LinkEvent one{};
    CHECK(!m.on_frame(0, 0, one));
    for (uint32_t t = 200; t <= 1000; t += 200) m.on_frame(0, t, one);
    CHECK(m.fresh(0, 3000));
    CHECK_EQ(m.tick(3000, ev, 3), 0u);        // exactly 2 s since last frame
    CHECK_EQ(m.tick(3001, ev, 3), 1u);
    CHECK_EQ(ev[0].type, UMSF_EV_LINK_LOSS);
    CHECK_EQ(ev[0].node, 0);
    CHECK_EQ(ev[0].value_x1000, 2001);
    CHECK_EQ(m.state(0), (LinkMonitor<3>::State)LinkMonitor<3>::LOST);
    CHECK_EQ(m.tick(9000, ev, 3), 0u);        // reported once
    CHECK(m.on_frame(0, 11000, one));
    CHECK_EQ(one.type, UMSF_EV_LINK_RESTORED);
    CHECK_EQ(one.value_x1000, 10000);         // 10 s outage since last frame
    // BLE disconnect -> immediate loss; never-connected node -> no event
    m.on_frame(1, 12000, one);
    CHECK(m.on_disconnect(1, 12500, one));
    CHECK_EQ(one.value_x1000, 500);
    CHECK(!m.on_disconnect(2, 12500, one));
    CHECK_EQ(m.age_ms(2, 12500), UINT32_MAX);
}

TEST(gw_parse_site_ack) {
    SiteAck a;
    const char *ok = "{ \"device_id\" : \"A01\", \"boot_id\": 1, \"ack_up_to_seq\": 13 }";
    CHECK(parse_site_ack(ok, std::strlen(ok), a));
    CHECK_STR(a.device_id, "A01");
    CHECK_EQ(a.boot_id, 1);
    CHECK_EQ(a.ack_up_to_seq, 13u);
    const char *bad[] = {
        "{\"device_id\":\"A01\",\"boot_id\":1}",
        "{\"device_id\":\"TOOLONG\",\"boot_id\":1,\"ack_up_to_seq\":2}",
        "{\"device_id\":\"A01\",\"boot_id\":-1,\"ack_up_to_seq\":2}",
        "{\"device_id\":\"A01\",\"boot_id\":70000,\"ack_up_to_seq\":2}",
        "{\"device_id\":A01,\"boot_id\":1,\"ack_up_to_seq\":2}",
        "not json"};
    for (const char *b : bad) CHECK(!parse_site_ack(b, std::strlen(b), a));
}

TEST(gw_allowlist) {
    const EnrolledNode t[] = {
        {"A01", "24:6F:28:AA:BB:01", UMSF_SRC_PERSONNEL, 123456, 1, "Z1", false},
        {"S01", "24:6f:28:aa:bb:02", UMSF_SRC_STATIONARY, 654321, 1, "Z1", true}};
    CHECK_EQ(find_enrolled_by_addr(t, 2, "24:6f:28:aa:bb:01"), 0);
    CHECK_EQ(find_enrolled_by_addr(t, 2, "24:6F:28:AA:BB:02"), 1);
    CHECK_EQ(find_enrolled_by_addr(t, 2, "24:6f:28:aa:bb:03"), -1);
    CHECK_EQ(find_enrolled_by_id(t, 2, "S01"), 1);
    CHECK_EQ(find_enrolled_by_id(t, 2, "X99"), -1);
}
