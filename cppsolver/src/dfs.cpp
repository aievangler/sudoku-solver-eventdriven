#include "dfs.hpp"
#include "propagation.hpp"
#include "scoring.hpp"
#include "trail.hpp"
#include <algorithm>

bool dfs(SolverState& S){
    if(S.is_solved()) return true;

    int c = select_mrv_cell(S);
    if(c < 0) return true; // solved

    std::vector<int> cand; cand.reserve(9);
    generate_candidates(S, c, cand);
    compute_scarcity(S);
    // Order candidates by descending score
    std::array<float,9> scores{};
    std::sort(cand.begin(), cand.end(), [&](int a, int b){
        return score_digit(S, c, a) > score_digit(S, c, b);
    });

    for(int d : cand){
        size_t mark = S.trail->mark();
        if(place_digit(S, c, d) && propagate(S) && dfs(S)){
            return true;
        }
        S.trail->undo_to(S, mark);
    }
    return false;
}
