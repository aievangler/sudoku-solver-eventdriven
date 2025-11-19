#pragma once
#include "state.hpp"
#include <vector>

// Compute scarcity[d] = number of candidate cells for digit d
void compute_scarcity(SolverState& S);

// Choose MRV cell (fewest candidates); returns -1 if solved.
int select_mrv_cell(const SolverState& S);

// Generate candidate digits for a cell into out vector (0..8).
void generate_candidates(const SolverState& S, int cell, std::vector<int>& out);
void generate_candidates_from_mask(uint16_t mask, std::vector<int>& out);

// Simple score for ordering candidates (higher is better).
float score_digit(const SolverState& S, int cell, int d);

// Select a secondary "pressure" cell near px for dual activation.
int select_pressure_cell(const SolverState& S, int px);
