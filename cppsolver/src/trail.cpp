#include "trail.hpp"
#include "state.hpp"
#include "geometry.hpp"
#include <cassert>

void Trail::undo_to(SolverState& S, size_t to_index){
    while(log.size() > to_index){
        auto e = log.back(); log.pop_back();
        int c = e.cell, d = e.digit;
        uint16_t oldm = e.old_mask;
        uint16_t curm = S.cell_mask[c];

        // Restore mask first
        S.cell_mask[c] = oldm;

        // Adjust B[d] bit for this cell using old/new mask relationship
        auto had_d_before = (oldm >> d) & 1u;
        auto has_d_now    = (curm >> d) & 1u; // before undo
        if(had_d_before && !has_d_now){
            // We had removed d at (c), restore it
            if(c<64) S.B[d].lo |= (1ULL<<c); else S.B[d].hi |= (1ULL<<(c-64));
            // Increment unit counts for the 3 units of c
            const auto& U = geom::CELL_UNITS[c];
            for(int ui=0; ui<3; ++ui) ++S.unit_digit_count[U[ui]][d];
        } else if(!had_d_before && has_d_now){
            // In rare cases, a PLACE removed d from c; old mask did not have d (should be rare)
            if(c<64) S.B[d].lo &= ~(1ULL<<c); else S.B[d].hi &= ~(1ULL<<(c-64));
            const auto& U = geom::CELL_UNITS[c];
            for(int ui=0; ui<3; ++ui) --S.unit_digit_count[U[ui]][d];
        }

        // Restore cell_value if needed
        if(e.type == TrailType::PLACE){
            S.cell_value[c] = 0;
        }
    }
    S.contradiction = false;
    // Any queues/enqueue flags left over belong to the abandoned branch.
    S.q_l4.clear();
    S.q_l1.clear();
    S.q_lock.clear();
    S.enq_l4.fill(0);
    S.enq_l1.fill(0);
    S.enq_lock.fill(0);
}
