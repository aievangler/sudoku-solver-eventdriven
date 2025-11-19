#pragma once
#include "state.hpp"

// Place digit d (0..8) in cell c (0..80). Returns false on contradiction.
bool place_digit(SolverState& S, int c, int d);

// Eliminate digit d (0..8) from cell c (0..80). Returns false on contradiction or no-op true.
bool eliminate_digit(SolverState& S, int c, int d);

// Process all queues to a fixpoint. Returns false on contradiction.
bool propagate(SolverState& S);
