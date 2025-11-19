#pragma once
#include <vector>
#include <cstdint>

struct SolverState;

enum class TrailType : uint8_t { PLACE=0, ELIM=1 };

struct TrailEntry {
    TrailType type;
    uint8_t cell;
    uint8_t digit;       // 0..8
    uint16_t old_mask;   // previous cell_mask[cell]
};

struct Trail {
    std::vector<TrailEntry> log;
    void reserve(size_t n){ log.reserve(n); }
    inline size_t mark() const { return log.size(); }

    inline void push_place(int cell, int digit, uint16_t old_mask){
        log.push_back(TrailEntry{TrailType::PLACE, (uint8_t)cell, (uint8_t)digit, old_mask});
    }
    inline void push_elim(int cell, int digit, uint16_t old_mask){
        log.push_back(TrailEntry{TrailType::ELIM, (uint8_t)cell, (uint8_t)digit, old_mask});
    }

    void undo_to(SolverState& S, size_t to_index);
};
