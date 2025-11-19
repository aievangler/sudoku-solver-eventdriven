# cppsolver (v10-port scaffold)

This repository is a **ready-to-build C++ scaffold** for your v10 Python solver:
- Event-driven propagation (L4, L1, locking)
- Bitboards (81-bit masks)
- Trail + exact undo
- MRV + influence + scarcity heuristic
- DFS with fixpoint propagation

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
