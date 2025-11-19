#include "dfs.hpp"
#include "propagation.hpp"
#include "scoring.hpp"
#include "trail.hpp"
#include <algorithm>

static bool dfs_single_node(SolverState& S, const SolverConfig& cfg, int depth);
static bool dfs_dual_node(SolverState& S, const SolverConfig& cfg, int depth);
static bool dfs_with_py(SolverState& S, const SolverConfig& cfg, int depth, int px);

static inline bool should_use_py(const SolverState& S,
                                 const SolverConfig& cfg,
                                 int depth,
                                 int mrv_px) {
    const DualConfig& dc = cfg.dual;
    if (!dc.enabled) return false;
    if (mrv_px > dc.max_mrv_px) return false;
    if (dc.require_flat_prop && S.last_prop_placements > 0) return false;
    if (depth < dc.min_depth) return false;
    if (depth > dc.max_depth) return false;
    return true;
}

bool dfs_single(SolverState& S, const SolverConfig& cfg) {
    return dfs_single_node(S, cfg, 0);
}

static bool dfs_single_node(SolverState& S, const SolverConfig& cfg, int depth) {
    (void)cfg;
    if (S.is_solved()) return true;

    int c = select_mrv_cell(S);
    if (c < 0) return true;

    uint16_t mask = S.cell_mask[c];
    std::vector<int> cand; cand.reserve(9);
    generate_candidates_from_mask(mask, cand);
    compute_scarcity(S);
    std::sort(cand.begin(), cand.end(), [&](int a, int b){
        return score_digit(S, c, a) > score_digit(S, c, b);
    });

    for (int d : cand) {
        size_t mark = S.trail->mark();
        if (!place_digit(S, c, d)) {
            S.trail->undo_to(S, mark);
            continue;
        }
        if (!propagate(S)) {
            S.trail->undo_to(S, mark);
            continue;
        }
        if (dfs_single_node(S, cfg, depth + 1)) {
            return true;
        }
        S.trail->undo_to(S, mark);
    }
    return false;
}

bool dfs_dual(SolverState& S, const SolverConfig& cfg) {
    return dfs_dual_node(S, cfg, 0);
}

static bool dfs_dual_node(SolverState& S, const SolverConfig& cfg, int depth) {
    if (S.is_solved()) return true;

    int px = select_mrv_cell(S);
    if (px < 0) return true;

    uint16_t mask_px = S.cell_mask[px];
    int mrv_px = popcount9(mask_px);

    std::vector<int> cand_x; cand_x.reserve(9);
    generate_candidates_from_mask(mask_px, cand_x);
    compute_scarcity(S);
    std::sort(cand_x.begin(), cand_x.end(), [&](int a, int b){
        return score_digit(S, px, a) > score_digit(S, px, b);
    });

    for (int dx : cand_x) {
        size_t mark = S.trail->mark();
        if (!place_digit(S, px, dx)) {
            S.trail->undo_to(S, mark);
            continue;
        }
        if (!propagate(S)) {
            S.trail->undo_to(S, mark);
            continue;
        }

        if (should_use_py(S, cfg, depth, mrv_px)) {
            if (dfs_with_py(S, cfg, depth + 1, px)) {
                return true;
            }
        }

        if (dfs_dual_node(S, cfg, depth + 1)) {
            return true;
        }

        S.trail->undo_to(S, mark);
    }
    return false;
}

static bool dfs_with_py(SolverState& S,
                        const SolverConfig& cfg,
                        int depth,
                        int px) {
    const DualConfig& dc = cfg.dual;
    int py = select_pressure_cell(S, px);
    if (py < 0) return false;

    uint16_t mask_py = S.cell_mask[py];
    if (mask_py == 0) return false;

    std::vector<int> cand_y; cand_y.reserve(9);
    generate_candidates_from_mask(mask_py, cand_y);
    compute_scarcity(S);
    std::sort(cand_y.begin(), cand_y.end(), [&](int a, int b){
        return score_digit(S, py, a) > score_digit(S, py, b);
    });

    int limit = static_cast<int>(cand_y.size());
    if (dc.max_py_candidates > 0) {
        limit = std::min(limit, dc.max_py_candidates);
    }

    for (int i = 0; i < limit; ++i) {
        int dy = cand_y[i];
        size_t mark2 = S.trail->mark();
        if (!place_digit(S, py, dy)) {
            S.trail->undo_to(S, mark2);
            continue;
        }
        if (!propagate(S)) {
            S.trail->undo_to(S, mark2);
            continue;
        }
        if (dfs_dual_node(S, cfg, depth + 1)) {
            return true;
        }
        S.trail->undo_to(S, mark2);
    }
    return false;
}
