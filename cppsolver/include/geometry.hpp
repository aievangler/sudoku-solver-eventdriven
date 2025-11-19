#pragma once
#include <array>
#include <cstdint>

namespace geom {

// 81-cell indexing: row-major 0..80
extern std::array<int,81> ROW;
extern std::array<int,81> COL;
extern std::array<int,81> BOX;

// Unit ids: 0..8 rows, 9..17 cols, 18..26 boxes
extern std::array<std::array<int,3>,81> CELL_UNITS;

// Masks (each mask is 81 bits split into two uint64 limbs: lo [0..63], hi [64..80])
struct Bits81 {
    uint64_t lo; // bits 0..63
    uint64_t hi; // bits 64..80 (only 17 bits used)

    constexpr Bits81(uint64_t lo_=0, uint64_t hi_=0) : lo(lo_), hi(hi_) {}
};

inline bool any(Bits81 x){ return (x.lo | x.hi) != 0ULL; }

inline int popcnt(Bits81 x){
    return __builtin_popcountll(x.lo) + __builtin_popcountll(x.hi);
}
inline Bits81 band(Bits81 a, Bits81 b){ return Bits81{a.lo & b.lo, a.hi & b.hi}; }
inline Bits81 bor (Bits81 a, Bits81 b){ return Bits81{a.lo | b.lo, a.hi | b.hi}; }
inline Bits81 bxor(Bits81 a, Bits81 b){ return Bits81{a.lo ^ b.lo, a.hi ^ b.hi}; }
inline Bits81 bnot(Bits81 a){ 
    // negate only valid bits (81)
    const uint64_t HI_MASK = (1ULL<<17) - 1ULL; // lower 17 bits valid
    return Bits81{~a.lo, (~a.hi) & HI_MASK};
}

// Clear bit i (0..80), Set bit i, Test bit i
inline void set_bit(Bits81& m, int i){
    if(i < 64) m.lo |= (1ULL<<i); else m.hi |= (1ULL<<(i-64));
}
inline void clr_bit(Bits81& m, int i){
    if(i < 64) m.lo &= ~(1ULL<<i); else m.hi &= ~(1ULL<<(i-64));
}
inline bool test_bit(Bits81 m, int i){
    if(i < 64) return (m.lo >> i) & 1ULL; else return (m.hi >> (i-64)) & 1ULL;
}

// Return index of least significant set bit; undefined if mask==0.
inline int ctz(Bits81 m){
    if(m.lo) return __builtin_ctzll(m.lo);
    return 64 + __builtin_ctzll(m.hi);
}

// Precomputed masks
extern std::array<Bits81, 9> ROW_MASK;
extern std::array<Bits81, 9> COL_MASK;
extern std::array<Bits81, 9> BOX_MASK;
extern std::array<Bits81,81> PEER_MASK;          // mask of peers for each cell
extern std::array<Bits81,27> UNIT_MASK;          // 27 units
extern std::array<std::array<Bits81,3>,9> BOX_ROW_MASK; // [box][0..2]
extern std::array<std::array<Bits81,3>,9> BOX_COL_MASK; // [box][0..2]

void init();    // must be called once at startup

} // namespace geom
