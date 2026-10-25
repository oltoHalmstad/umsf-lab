// umsf_test.h - minimal test harness. Host build: self-contained runner (test_main.cpp).
// PlatformIO `pio test -e native`: define UMSF_USE_UNITY and the same tests run under Unity.
#pragma once
#include <cmath>
#include <cstdio>
#include <cstring>

namespace umsf_test {
struct Case { const char *name; void (*fn)(); };
inline Case g_cases[256];
inline int g_ncases = 0;
inline int g_failures = 0;
inline int g_checks = 0;
struct Reg { Reg(const char *n, void (*f)()) { if (g_ncases < 256) g_cases[g_ncases++] = Case{n, f}; } };
inline void fail(const char *file, int line, const char *msg) {
    ++g_failures;
    std::printf("  FAIL %s:%d: %s\n", file, line, msg);
}
}  // namespace umsf_test

#define TEST(name) \
    static void name(); \
    static umsf_test::Reg reg_##name(#name, name); \
    static void name()

#ifdef UMSF_USE_UNITY
#include <unity.h>
#define CHECK(c) TEST_ASSERT_TRUE_MESSAGE((c), #c)
#define CHECK_EQ(a, b) TEST_ASSERT_EQUAL_INT64_MESSAGE((long long)(b), (long long)(a), #a " == " #b)
#define CHECK_STR(a, b) TEST_ASSERT_EQUAL_STRING_MESSAGE((b), (a), #a " == " #b)
#define CHECK_NEAR(a, b, tol) TEST_ASSERT_DOUBLE_WITHIN_MESSAGE((tol), (b), (a), #a " ~ " #b)
#else
#define CHECK(c) do { ++umsf_test::g_checks; if (!(c)) umsf_test::fail(__FILE__, __LINE__, #c); } while (0)
#define CHECK_EQ(a, b) do { ++umsf_test::g_checks; long long _a = (long long)(a), _b = (long long)(b); \
    if (_a != _b) { char _m[256]; std::snprintf(_m, sizeof _m, "%s == %s (%lld vs %lld)", #a, #b, _a, _b); \
    umsf_test::fail(__FILE__, __LINE__, _m); } } while (0)
#define CHECK_STR(a, b) do { ++umsf_test::g_checks; const char *_a = (a), *_b = (b); \
    if (std::strcmp(_a, _b) != 0) { char _m[1024]; std::snprintf(_m, sizeof _m, "%s\n    got:      %s\n    expected: %s", #a, _a, _b); \
    umsf_test::fail(__FILE__, __LINE__, _m); } } while (0)
#define CHECK_NEAR(a, b, tol) do { ++umsf_test::g_checks; double _a = (a), _b = (b); \
    if (std::fabs(_a - _b) > (tol)) { char _m[256]; std::snprintf(_m, sizeof _m, "%s ~ %s (%g vs %g)", #a, #b, _a, _b); \
    umsf_test::fail(__FILE__, __LINE__, _m); } } while (0)
#endif
