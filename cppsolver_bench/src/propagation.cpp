#include "propagation.hpp"
#include "trail.hpp"
#include "geometry.hpp"
#include <cassert>

using geom::Bits81;
using geom::band;
using geom::bor;
using geom::bnot;
using geom::any;
using geom::ctz;
using geom::popcnt;

static inline void enqueue_l4(SolverState& S, int c){
    if(!S.enq_l4[c]){ S.enq_l4[c]=1; S.q_l4.push_back(c); }
}
static inline void enqueue_l1(SolverState& S, int unit, int d){
    int idx = unit*9 + d;
    if(!S.enq_l1[idx]){ S.enq_l1[idx]=1; S.q_l1.push_back((unit<<4)|d); }
}
static inline void enqueue_lock(SolverState& S, int box, int d){
    int idx = box*9 + d;
    if(!S.enq_lock[idx]){ S.enq_lock[idx]=1; S.q_lock.push_back((box<<4)|d); }
}

bool eliminate_digit(SolverState& S, int c, int d){
    uint16_t m = S.cell_mask[c];
    uint16_t bit = 1u<<d;
    if((m & bit)==0) return true; // already eliminated

    // Trail and update cell mask
    S.trail->push_elim(c, d, m);
    m &= ~bit;
    S.cell_mask[c] = m;

    // Clear B[d] bit
    if(c<64) S.B[d].lo &= ~(1ULL<<c); else S.B[d].hi &= ~(1ULL<<(c-64));

    // Update unit counts (three units for cell c)
    const auto& U = geom::CELL_UNITS[c];
    for(int ui=0; ui<3; ++ui){
        int u = U[ui];
        int newcnt = --S.unit_digit_count[u][d];
        if(newcnt == 1) enqueue_l1(S, u, d);
        if(newcnt < 0){ S.contradiction=true; return false; }
    }
    // No candidates left
    if(m == 0u){ S.contradiction=true; return false; }

    // If mask is a single, enqueue L4 placement
    if((m & (m-1)) == 0) enqueue_l4(S, c);

    // Locking: changes inside box may affect pointing/claiming; enqueue (box,d)
    enqueue_lock(S, geom::BOX[c], d);

    return true;
}

bool place_digit(SolverState& S, int c, int d){
    // If already placed with same digit, ok; if placed differently -> contradiction
    if (S.cell_value[c]) {
        if (S.cell_value[c] != d + 1){ S.contradiction=true; return false; }
        return true;
    }
    uint16_t old = S.cell_mask[c];
    if(((old>>d)&1u)==0){ S.contradiction=true; return false; }
    // Trail entry remembers old mask; we enforce the single after wiping other digits
    S.trail->push_place(c, d, old);

    // Remove other digits from this cell (update counts/B and possibly L1)
    for(int x=0; x<9; ++x){
        if(x==d) continue;
        if((old>>x)&1u){
            if(!eliminate_digit(S, c, x)) return false;
        }
    }
    // Now enforce single mask and set value
    S.cell_mask[c] = (uint16_t)(1u<<d);
    S.cell_value[c] = (uint8_t)(d+1);

    // Eliminate d from peers
    auto peers = geom::PEER_MASK[c];
    Bits81 affected = geom::band(S.B[d], peers); // cells that currently still allow d among peers

    // Iterate affected peers to update their cell masks and counters/events
    while(geom::any(affected)){
        int p = geom::ctz(affected);
        if(p<64) affected.lo &= (affected.lo-1);
        else     affected.hi &= (affected.hi-1);
        // For p, remove digit d
        uint16_t pm = S.cell_mask[p];
        if(pm & (1u<<d)){
            S.trail->push_elim(p, d, pm);
            pm &= ~(1u<<d);
            S.cell_mask[p] = pm;
            if(p<64) S.B[d].lo &= ~(1ULL<<p); else S.B[d].hi &= ~(1ULL<<(p-64));
            const auto& U = geom::CELL_UNITS[p];
            for(int ui=0; ui<3; ++ui){
                int u = U[ui];
                int newcnt = --S.unit_digit_count[u][d];
                if(newcnt == 1) enqueue_l1(S, u, d);
                if(newcnt < 0){ S.contradiction=true; return false; }
            }
            if(pm == 0u){ S.contradiction=true; return false; }
            if((pm & (pm-1)) == 0) enqueue_l4(S, p);
            enqueue_lock(S, geom::BOX[p], d);
        }
    }
    return true;
}

// Pop helpers (stale-safe)
static inline bool try_pop_L4(SolverState& S, int& c_out){
    while(!S.q_l4.empty()){
        int c = S.q_l4.back(); S.q_l4.pop_back();
        S.enq_l4[c]=0;
        if(!S.cell_value[c] && (__builtin_popcount((unsigned)S.cell_mask[c])==1)){
            c_out = c; return true;
        }
    }
    return false;
}
static inline bool try_pop_L1(SolverState& S, int& unit_out, int& d_out){
    while(!S.q_l1.empty()){
        int t = S.q_l1.back(); S.q_l1.pop_back();
        int u = t>>4, d = t & 15;
        S.enq_l1[u*9+d]=0;
        if(S.unit_digit_count[u][d]==1){
            unit_out=u; d_out=d; return true;
        }
    }
    return false;
}
static inline bool try_pop_lock(SolverState& S, int& box_out, int& d_out){
    while(!S.q_lock.empty()){
        int t = S.q_lock.back(); S.q_lock.pop_back();
        int b = t>>4, d = t & 15;
        S.enq_lock[b*9+d]=0;
        // Always process; caller will check if a lock exists
        box_out=b; d_out=d; return true;
    }
    return false;
}

static bool process_lock_event(SolverState& S, int b, int d){
    // Determine if all candidates of (box b, digit d) lie in a single row-in-box or col-in-box.
    auto M = geom::band(S.B[d], geom::BOX_MASK[b]);
    if(!geom::any(M)) return true; // nothing to do
    // Try rows-in-box
    for(int rr=0; rr<3; ++rr){
        auto Mr = geom::band(M, geom::BOX_ROW_MASK[b][rr]);
        if(geom::any(Mr)){
            // if all M lies within this row-in-box:
            auto diff = geom::bxor(M, Mr);
            if(!geom::any(diff)){
                // eliminate d from the rest of the global row outside the box
                int global_r = (b/3)*3 + rr;
                auto target = geom::band(S.B[d], geom::band(geom::ROW_MASK[global_r], geom::bnot(geom::BOX_MASK[b])));
                while(geom::any(target)){
                    int c = geom::ctz(target);
                    if(c<64) target.lo &= (target.lo-1); else target.hi &= (target.hi-1);
                    if(!eliminate_digit(S, c, d)) return false;
                }
                return true;
            }
        }
    }
    // Try cols-in-box
    for(int cc=0; cc<3; ++cc){
        auto Mc = geom::band(M, geom::BOX_COL_MASK[b][cc]);
        if(geom::any(Mc)){
            auto diff = geom::bxor(M, Mc);
            if(!geom::any(diff)){
                int global_c = (b%3)*3 + cc;
                auto target = geom::band(S.B[d], geom::band(geom::COL_MASK[global_c], geom::bnot(geom::BOX_MASK[b])));
                while(geom::any(target)){
                    int c = geom::ctz(target);
                    if(c<64) target.lo &= (target.lo-1); else target.hi &= (target.hi-1);
                    if(!eliminate_digit(S, c, d)) return false;
                }
                return true;
            }
        }
    }
    return true;
}

bool propagate(SolverState& S){
    // Drain queues to fixpoint
    S.last_prop_placements = 0;
    int c;
    int u,d, b;
    while(true){
        bool progressed=false;
        while(try_pop_L4(S, c) && !S.contradiction){
            // place the only digit in this cell
            int dig = __builtin_ctz((unsigned)S.cell_mask[c]);
            // guard: do not double-place
            if(!S.cell_value[c]){
                if(!place_digit(S, c, dig)) return false;
                ++S.last_prop_placements;
                progressed=true;
            }
        }
        if(S.contradiction) return false;

        while(try_pop_L1(S, u, d) && !S.contradiction){
            // locate unique cell for (u,d)
            auto mask = geom::band(S.B[d], geom::UNIT_MASK[u]);
            if(geom::any(mask)){
                int cell = geom::ctz(mask);
                if(!place_digit(S, cell, d)) return false;
                ++S.last_prop_placements;
                progressed=true;
            }
        }
        if(S.contradiction) return false;

        while(try_pop_lock(S, b, d) && !S.contradiction){
            if(!process_lock_event(S, b, d)) return false;
            progressed=true; // may be false if no lock existed; harmless
        }
        if(S.contradiction) return false;

        if(!progressed) break;
    }
    return true;
}
