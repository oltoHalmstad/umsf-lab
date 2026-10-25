// PlatformIO native test entry point: `pio test -e native`.
// Runs the same test cases as test/host (g++ Makefile) under the Unity framework.
#ifndef UMSF_USE_UNITY
#define UMSF_USE_UNITY
#endif
#include <unity.h>

#include "../host/test_buffer.cpp"
#include "../host/test_features.cpp"
#include "../host/test_frag.cpp"
#include "../host/test_gwcore.cpp"
#include "../host/test_proto.cpp"

void setUp() {}
void tearDown() {}

int main() {
    UNITY_BEGIN();
    for (int i = 0; i < umsf_test::g_ncases; ++i)
        UnityDefaultTestRun(umsf_test::g_cases[i].fn, umsf_test::g_cases[i].name, __LINE__);
    return UNITY_END();
}
