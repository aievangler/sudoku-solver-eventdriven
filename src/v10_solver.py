"""
CLI runner for the v10 Sudoku solver core.

This wraps the primitives from ``v10_core`` with basic argument parsing so the
solver can be invoked on single puzzles or batches of puzzles, mirroring the
lightweight tooling used for previous solver generations.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import List, Optional

from v10_core import (
    DFSStats,
    K_CAND,
    SINGLE_WAVE_CAP,
    build_S0,
    solve_v10,
)


@dataclass
class V10Config:
    single_wave_cap: int = SINGLE_WAVE_CAP
    k_cand: int = K_CAND
    use_l2: bool = False
    l2_budget_node: int = 0
    l2_budget_puzzle: int = 0


def _extract_puzzle(text: str) -> str:
    digits = [ch for ch in text if ch in "0123456789."]
    if len(digits) < 81:
        raise ValueError("Puzzle input must contain at least 81 characters.")
    return "".join(digits[:81])


def _load_puzzles(puzzle: Optional[str], puzzle_file: Optional[Path]) -> List[str]:
    puzzles: List[str] = []
    if puzzle:
        puzzles.append(_extract_puzzle(puzzle))
    if puzzle_file:
        for raw in puzzle_file.read_text().splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            puzzles.append(_extract_puzzle(stripped))
    return puzzles


def solve_once_v10(puzzle: str, cfg: V10Config) -> dict:
    """Build S₀, run DFS, and capture stats/timings."""
    total_start = perf_counter()

    s0_start = perf_counter()
    state = build_S0(puzzle)
    s0_time = perf_counter() - s0_start

    stats = DFSStats()
    solve_start = perf_counter()
    solved = solve_v10(
        state,
        stats,
        depth=0,
        k_candidates=cfg.k_cand,
        use_l2=cfg.use_l2,
        l2_budget_node=cfg.l2_budget_node,
        l2_budget_puzzle=cfg.l2_budget_puzzle,
    )
    solve_time = perf_counter() - solve_start
    total_time_ms = (perf_counter() - total_start) * 1000.0
    s0_time_ms = s0_time * 1000.0
    solve_time_ms = solve_time * 1000.0

    solution = None
    if solved and all(val != -1 for val in state.value):
        solution = "".join(str(val + 1) for val in state.value)

    stats_dict = {
        "nodes": stats.nodes,
        "placements": stats.placements,
        "max_depth": stats.max_depth,
        "ns_events": stats.ns_events,
        "hs_events": stats.hs_events,
        "l2_uses": stats.l2_uses,
    }

    return {
        "time_ms": total_time_ms,
        "success": solved,
        "solution": solution,
        "stats": stats,
        "stats_dict": stats_dict,
        "s0_time_ms": s0_time_ms,
        "solve_time_ms": solve_time_ms,
    }


def _format_board(solution: str) -> str:
    rows = [solution[r * 9 : (r + 1) * 9] for r in range(9)]
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI runner for the v10 core solver")
    parser.add_argument("--puzzle", help="Single puzzle string (81 chars).")
    parser.add_argument("--puzzle-file", type=Path, help="Path to a file with puzzles.")
    parser.add_argument("--runs", type=int, default=1, help="Runs per puzzle.")
    parser.add_argument("--single-wave-cap", type=int, default=SINGLE_WAVE_CAP)
    parser.add_argument("--k-cand", type=int, default=K_CAND)
    parser.add_argument("--use-l2", action="store_true", help="Enable optional L2 probe.")
    parser.add_argument("--l2-budget-node", type=int, default=0, help="L2 evaluations per node.")
    parser.add_argument(
        "--l2-budget-puzzle", type=int, default=0, help="Total L2 evaluations per puzzle."
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress per-run logs.")
    args = parser.parse_args()

    puzzles = _load_puzzles(args.puzzle, args.puzzle_file)
    if not puzzles:
        parser.error("No puzzles provided.")

    cfg = V10Config(
        single_wave_cap=max(1, args.single_wave_cap),
        k_cand=max(1, args.k_cand),
        use_l2=args.use_l2,
        l2_budget_node=max(0, args.l2_budget_node),
        l2_budget_puzzle=max(0, args.l2_budget_puzzle),
    )

    overall_start = perf_counter()
    all_times: List[float] = []

    for idx, puzzle in enumerate(puzzles):
        for run in range(args.runs):
            result = solve_once_v10(puzzle, cfg)
            status = "OK" if result["success"] else "FAIL"
            if not args.quiet:
                stats = result["stats_dict"]
                print(
                    f"[p{idx} run {run+1}] {status} "
                    f"s0={result['s0_time_ms']:.2f}ms "
                    f"solve={result['solve_time_ms']:.2f}ms "
                    f"nodes={stats['nodes']} depth={stats['max_depth']} "
                    f"ns={stats['ns_events']} hs={stats['hs_events']} "
                    f"l2={stats['l2_uses']}"
                )
            if result["solution"]:
                print(_format_board(result["solution"]))
            if result["success"]:
                all_times.append(result["time_ms"])

    wall_ms = (perf_counter() - overall_start) * 1000.0
    if all_times:
        min_ms = min(all_times)
        max_ms = max(all_times)
        med_ms = median(all_times)
        mean_ms = sum(all_times) / len(all_times)
        total_core_s = sum(all_times) / 1000.0
    else:
        min_ms = max_ms = med_ms = mean_ms = total_core_s = 0.0

    print(
        f"Solved {len(all_times)}/{len(puzzles) * args.runs} runs. "
        f"mean={mean_ms:.2f} ms, median={med_ms:.2f} ms, wall={wall_ms:.2f} ms."
    )
    print(
        f"Aggregate timing (ms): min {min_ms:.2f} | median {med_ms:.2f} | "
        f"mean {mean_ms:.2f} | max {max_ms:.2f}"
    )
    print(
        f"Total core solve time: {total_core_s:.2f} s | mean per puzzle: {mean_ms:.2f} ms"
    )


if __name__ == "__main__":
    main()
