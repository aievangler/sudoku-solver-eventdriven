#pragma once
#include <string>
#include "state.hpp"
#include "trail.hpp"
struct SolverTimings {
    double init_wall_ms = 0.0;
    double init_cpu_ms = 0.0;
    double propagate_wall_ms = 0.0;
    double propagate_cpu_ms = 0.0;
    double search_wall_ms = 0.0;
    double search_cpu_ms = 0.0;
};

class SudokuSolver {
public:
    explicit SudokuSolver(const SolverConfig& cfg = SolverConfig());
    bool solve(const std::string& puzzle, SolverTimings* timings = nullptr);
    std::string solution_string() const;
    const SolverState& state() const { return S_; }
    void set_config(const SolverConfig& cfg){ config_ = cfg; }

private:
    SolverState S_;
    Trail trail_;
    SolverConfig config_{};
};
