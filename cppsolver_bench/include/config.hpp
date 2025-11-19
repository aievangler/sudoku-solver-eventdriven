#pragma once
#include <cstdint>

namespace cfg {
// Enable lightweight runtime checks in debug builds
#ifndef NDEBUG
constexpr bool kDebugChecks = true;
#else
constexpr bool kDebugChecks = false;
#endif

// Queue capacities (upper bounds).
constexpr int kMaxL4Queue = 81;
constexpr int kMaxL1Queue = 27*9;
constexpr int kMaxLockQueue = 27*9;
} // namespace cfg
