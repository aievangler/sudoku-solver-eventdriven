# cppsolver (v10-port scaffold)

This repository is a **ready-to-build C++ scaffold** for your v10 Python solver:
- Event-driven propagation (L4, L1, locking)
- Bitboards (81-bit masks)
- Trail + exact undo
- MRV + influence + scarcity heuristic
- DFS with fixpoint propagation

## Build the C++ solvers

Two copies of the C++ solver are provided:

- `cppsolver/`: the original executable that prints every solution (supports `--file` and `--timings`).
- `cppsolver_bench/`: a benchmark-oriented duplicate with an additional `--benchmark` mode and MRV short-circuit.

Build (example for Release with native flags + LTO):

```bash
cd cppsolver
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-march=native -flto"
cmake --build build -j

# optional benchmark copy
cd ../cppsolver_bench
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-march=native -flto"
cmake --build build -j
```

Run:

```bash
# normal solver
./cppsolver/build/cppsolver --file testFileSets/puzzles2_17_clue --timings

# benchmark mode: solves entire file without per-puzzle I/O and prints summary
./cppsolver_bench/build/cppsolver --file testFileSets/puzzles2_17_clue --benchmark
```

PlanRun integration (Python) now supports `--engine cpp` and the batch script `run_v7_v10.sh` automatically invokes the C++ solver after the V7/V10 presets.

## Build (macOS Apple Silicon)

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
./build/cppsolver                   # uses a default puzzle
./build/cppsolver "..........."     # or pass a puzzle string (81 chars)
```

## Where to add logic from your Python v10

- `src/propagation.cpp` has `place_digit`, `eliminate_digit`, `propagate`.
- `src/scoring.cpp` has MRV/influence/scarcity; adjust the scoring formula.
- `src/dfs.cpp` is the search loop.
- `src/state.cpp` builds initial candidates and queues.

## Notes

- This scaffold **builds and runs** now (with a simple sample puzzle).
- Hot code paths are marked and already use bitwise iteration.
- Add profiling (Instruments) once you wire in your exact rules.
