#pragma once
#include "state.hpp"
#include "config.hpp"
#include <vector>

bool dfs_single(SolverState& S, const SolverConfig& cfg);
bool dfs_dual(SolverState& S, const SolverConfig& cfg);
