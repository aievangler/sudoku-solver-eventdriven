"""
CLI runner for the extracted v7 core solver.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import List, Optional

try:
    from .v7new_core import SolverStats, build_S0, extract_solution, solve_v7new  # type: ignore[attr-defined]
except ImportError:  # script execution
    from v7new_core import SolverStats, build_S0, extract_solution, solve_v7new


@dataclass
class V7NewConfig:
    profile_core: bool = False
    timeout: Optional[float] = None


def solve_once_v7new(puzzle: str, cfg: V7NewConfig) -> dict:
    total_start = perf_counter()
    try:
        s0_start = perf_counter()
        state = build_S0(puzzle, profile_core=cfg.profile_core)
        s0_time_ms = (perf_counter() - s0_start) * 1000.0
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "time_ms": 0.0,
            "s0_time_ms": 0.0,
            "solve_time_ms": 0.0,
            "stats_dict": {"nodes": 0, "placements": 0},
            "solution": None,
        }

    stats = SolverStats()
    solve_start = perf_counter()
    solved = solve_v7new(state, stats, timeout=cfg.timeout)
    solve_time_ms = (perf_counter() - solve_start) * 1000.0
    total_time_ms = (perf_counter() - total_start) * 1000.0

    solution = extract_solution(state) if solved else None
    stats_dict = {
        "nodes": stats.nodes,
        "placements": stats.placements,
    }

    return {
        "success": solved,
        "error": None,
        "time_ms": total_time_ms,
        "s0_time_ms": s0_time_ms,
        "solve_time_ms": solve_time_ms,
        "stats_dict": stats_dict,
        "solution": solution,
    }


def _format_board(solution: str) -> str:
    rows = [solution[r * 9 : (r + 1) * 9] for r in range(9)]
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI runner for the v7 core solver")
    parser.add_argument("--puzzle", help="Single puzzle string (81 chars).")
    parser.add_argument("--puzzle-file", type=Path, help="Path to a file with puzzles.")
    parser.add_argument("--runs", type=int, default=1, help="Runs per puzzle.")
    parser.add_argument("--timeout", type=float, help="Per puzzle timeout in seconds.")
    parser.add_argument("--profile-core", action="store_true", help="Collect prop/score timings.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-run logs.")
    args = parser.parse_args()

    puzzles: List[str] = []
    if args.puzzle:
        puzzles.append(args.puzzle)
    if args.puzzle_file:
        for raw in args.puzzle_file.read_text().splitlines():
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            puzzles.append(stripped)
    if not puzzles:
        parser.error("No puzzles provided.")

    cfg = V7NewConfig(profile_core=args.profile_core, timeout=args.timeout)
    overall_start = perf_counter()
    all_times: List[float] = []

    for idx, puzzle in enumerate(puzzles):
        for run in range(args.runs):
            result = solve_once_v7new(puzzle, cfg)
            if not args.quiet:
                stats = result["stats_dict"]
                print(
                    f"[p{idx} run {run+1}] "
                    f"{'OK' if result['success'] else 'FAIL'} "
                    f"s0={result['s0_time_ms']:.2f}ms "
                    f"solve={result['solve_time_ms']:.2f}ms "
                    f"nodes={stats['nodes']} placements={stats['placements']}"
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

    total_runs = len(puzzles) * args.runs
    solved_runs = len(all_times)
    print(
        f"Solved {solved_runs}/{total_runs} runs. "
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
