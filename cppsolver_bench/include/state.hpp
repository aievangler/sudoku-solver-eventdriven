#pragma once
#include <array>
#include <vector>
#include <string>
#include <cstdint>
#include "geometry.hpp"
#include "config.hpp"

struct Trail; // forward

struct SolverState {
    // Candidates by digit (bitboard over 81 cells): B[d] has 1 where digit d is allowed.
    std::array<geom::Bits81, 9> B{};

    // Per-cell candidate mask (9 bits), bit 0..8 for digits 1..9
    std::array<uint16_t, 81> cell_mask{};

    // Current value in each cell: 0 if empty, else 1..9
    std::array<uint8_t, 81> cell_value{};

    // Unit-digit counts [27 units][9 digits]
    int unit_digit_count[27][9]{};

    // Queues (stale-safe policy)
    std::vector<int> q_l4;   // naked singles: store cell index
    std::vector<int> q_l1;   // hidden singles: encode (unit<<4)|digit (digit 0..8)
    std::vector<int> q_lock; // lock events: encode (box<<4)|digit

    // Enqueue flags (optional churn control)
    std::array<uint8_t, 81> enq_l4{};
    std::array<uint8_t, 27*9> enq_l1{};    // index = unit*9 + digit
    std::array<uint8_t, 9*9> enq_lock{};   // index = box*9 + digit

    // Global flags
    bool contradiction = false;

    // Scarcity cache (cells available per digit)
    std::array<int, 9> scarcity{};

    int last_prop_placements = 0;

    Trail* trail = nullptr; // set by owner

    void reset();
    void init_from_puzzle(const std::string& puzzle); // '.' or '0' means empty
    bool is_solved() const;
};

// Utility
inline int popcount9(uint16_t m){ return __builtin_popcount((unsigned)m); }
