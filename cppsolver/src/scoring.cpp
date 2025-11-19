#include "scoring.hpp"
#include "geometry.hpp"
#include <algorithm>

void compute_scarcity(SolverState& S){
    for(int d=0; d<9; ++d){
        S.scarcity[d] = geom::popcnt(S.B[d]);
    }
}

int select_mrv_cell(const SolverState& S){
    int best=-1, bestw=10;
    for(int c=0;c<81;++c){
        if(S.cell_value[c]) continue;
        int w = __builtin_popcount((unsigned)S.cell_mask[c]);
        if(w < bestw){ bestw=w; best=c; if(w==1) break; }
    }
    return best; // -1 means all filled
}

void generate_candidates(const SolverState& S, int cell, std::vector<int>& out){
    out.clear();
    uint16_t m = S.cell_mask[cell];
    while(m){
        int d = __builtin_ctz((unsigned)m);
        m &= (m-1);
        out.push_back(d);
    }
}

float score_digit(const SolverState& S, int cell, int d){
    // Influence approximation: how many peers currently allow digit d
    int inf = geom::popcnt( geom::band(S.B[d], geom::PEER_MASK[cell]) );
    // Scarcity: fewer cells -> prefer
    int sc  = S.scarcity[d];
    // Simple linear combination (tunable)
    return 2.0f * (float)inf + -1.0f * (float)sc;
}
