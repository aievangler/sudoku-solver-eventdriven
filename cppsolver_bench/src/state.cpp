#include "state.hpp"
#include "trail.hpp"
#include "geometry.hpp"
#include <cassert>
#include <cstring>
#include <algorithm>

void SolverState::reset(){
    std::fill(cell_mask.begin(), cell_mask.end(), 0);
    std::fill(cell_value.begin(), cell_value.end(), 0);
    for(int d=0; d<9; ++d){ B[d] = geom::Bits81{}; }
    for(int u=0; u<27; ++u) for(int d=0; d<9; ++d) unit_digit_count[u][d]=0;
    q_l4.clear(); q_l1.clear(); q_lock.clear();
    if(q_l4.capacity() < cfg::kMaxL4Queue) q_l4.reserve(cfg::kMaxL4Queue);
    if(q_l1.capacity() < cfg::kMaxL1Queue) q_l1.reserve(cfg::kMaxL1Queue);
    if(q_lock.capacity() < cfg::kMaxLockQueue) q_lock.reserve(cfg::kMaxLockQueue);
    enq_l4.fill(0); enq_l1.fill(0); enq_lock.fill(0);
    contradiction = false;
    scarcity.fill(0);
    last_prop_placements = 0;
}

bool SolverState::is_solved() const{
    for(int i=0;i<81;++i) if(!cell_value[i]) return false;
    return true;
}

void SolverState::init_from_puzzle(const std::string& puzzle){
    reset();
    // Initialize base candidates
    for(int i=0;i<81;++i){
        if(i < (int)puzzle.size()){
            char ch = puzzle[i];
            if(ch>='1' && ch<='9'){
                int d = (ch - '1');
                cell_mask[i] = (1u<<d);
                cell_value[i] = 0;          // leave 0, let place_digit set it
            }else{
                cell_mask[i] = 0x1FFu; // all digits allowed initially
                cell_value[i] = 0;
            }
        }else{
            cell_mask[i] = 0x1FFu;
            cell_value[i] = 0;
        }
        // Fill B[] from mask (as initial candidate set; placed cells will be fixed below)
        for(int d=0; d<9; ++d){
            if( (cell_mask[i] >> d) & 1u ){
                if(i<64) B[d].lo |= (1ULL<<i);
                else     B[d].hi |= (1ULL<<(i-64));
            }
        }
    }
    // Initialize unit counters from B (popcount of B[d] intersect unit)
    for(int u=0; u<27; ++u){
        auto um = geom::UNIT_MASK[u];
        for(int d=0; d<9; ++d){
            auto im = geom::band(B[d], um);
            unit_digit_count[u][d] = geom::popcnt(im);
        }
    }
    // Precompute scarcity
    for(int d=0; d<9; ++d){
        scarcity[d] = geom::popcnt(B[d]);
    }
    // Enqueue L4 for any singletons (givens or forced)
    for(int i=0;i<81;++i){
        if (__builtin_popcount((unsigned)cell_mask[i]) == 1) {
            q_l4.push_back(i);
        }
    }
}
