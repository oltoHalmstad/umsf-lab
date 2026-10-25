// Host test runner (g++). See test/host/Makefile.
#include "umsf_test.h"

int main() {
    int failed_cases = 0;
    for (int i = 0; i < umsf_test::g_ncases; ++i) {
        int before = umsf_test::g_failures;
        umsf_test::g_cases[i].fn();
        bool ok = umsf_test::g_failures == before;
        if (!ok) ++failed_cases;
        std::printf("[%s] %s\n", ok ? "PASS" : "FAIL", umsf_test::g_cases[i].name);
    }
    std::printf("\n%d test cases, %d passed, %d failed; %d checks, %d failed checks\n", umsf_test::g_ncases,
                umsf_test::g_ncases - failed_cases, failed_cases, umsf_test::g_checks, umsf_test::g_failures);
    return failed_cases ? 1 : 0;
}
