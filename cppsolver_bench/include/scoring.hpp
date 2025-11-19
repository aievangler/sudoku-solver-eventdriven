#pragma once
#include "state.hpp"
#include <vector>

// Compute scarcity[d] = number of candidate cells for digit d
void compute_scarcity(SolverState& S);

// Choose MRV cell (fewest candidates); returns -1 if solved.
int select_mrv_cell(const SolverState& S);

// Generate candidate digits for a cell into out vector (0..8).
void generate_candidates(const SolverState& S, int cell, std::vector<int>& out);

// Simple score for ordering candidates (higher is better).
float score_digit(const SolverState& S, int cell, int d);
