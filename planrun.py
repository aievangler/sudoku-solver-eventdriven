"""
PlanRun harness: multi-puzzle runner built on the v9_core engine.
"""
from __future__ import annotations

import argparse
import random
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import List, Optional
import subprocess

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from solver_db import SolverDatabase
from v9_core import MacroConfig, Rules, Stats, build_S0, dfs
from v10_core import K_CAND, SINGLE_WAVE_CAP
from v10_solver import V10Config, solve_once_v10
from v7new_solver import V7NewConfig, solve_once_v7new


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


def solve_once_v9(puzzle: str, rules: Rules, macro_cfg: MacroConfig) -> dict:
    s0_start = perf_counter()
    state = build_S0(puzzle, rules)
    s0_time = perf_counter() - s0_start
    solve_start = perf_counter()
    stats = Stats()
    solved = dfs(state, rules, stats, macro_cfg, depth=0)
    solve_time = perf_counter() - solve_start
    board = None
    if solved:
        from v9_core import count_solved

        if count_solved(state) == 81:
            board_rows = []
            for r in range(9):
                row_digits = []
                for c in range(9):
                    mask = state.cell_mask[r * 9 + c]
                    if mask and mask & (mask - 1) == 0:
                        digit = (mask & -mask).bit_length() - 1
                        row_digits.append(str(digit + 1))
                    else:
                        row_digits.append(".")
                board_rows.append("".join(row_digits))
            board = "\n".join(board_rows)
    return {
        "success": solved,
        "stats": stats,
        "s0_time_ms": s0_time * 1000.0,
        "solve_time_ms": solve_time * 1000.0,
        "board": board,
    }


def solve_dataset_cpp(file_path: Path, binary: Path, benchmark: bool) -> dict:
    start = perf_counter()
    cmd = ["env", "MallocNanoZone=0", str(binary), "--file", str(file_path)]
    if benchmark:
        cmd.append("--benchmark")
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed_ms = (perf_counter() - start) * 1000.0
    stdout_lines = proc.stdout.splitlines()
    if benchmark:
        summary = stdout_lines[-1] if stdout_lines else ""
        return {
            "success": proc.returncode == 0,
            "stats_dict": {"returncode": proc.returncode, "summary": summary},
            "s0_time_ms": 0.0,
            "solve_time_ms": elapsed_ms,
            "solutions": [],
        }
    else:
        return {
            "success": proc.returncode == 0,
            "stats_dict": {"returncode": proc.returncode, "solutions": len(stdout_lines)},
            "s0_time_ms": 0.0,
            "solve_time_ms": elapsed_ms,
            "solutions": stdout_lines,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="PlanRun harness for v9/v10 cores")
    parser.add_argument("--puzzle", help="Single puzzle string (81 chars).")
    parser.add_argument("--puzzle-file", type=Path, help="Path to a file with puzzles.")
    parser.add_argument("--start", type=int, default=0, help="0-based puzzle start index.")
    parser.add_argument("--count", type=int, help="Maximum puzzles to process.")
    parser.add_argument("--runs", type=int, default=1, help="Runs per puzzle.")
    parser.add_argument("--timing-reps", type=int, default=1, help="Dataset repetitions.")
    parser.add_argument("--shuffle-seed", type=int, default=1337, help="Shuffle seed.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-run logs.")
    parser.add_argument("--rules-profile", choices=["basic", "pairs", "full"], default="basic")
    parser.add_argument("--locks-mode", choices=["off", "l1", "all"], default="all")
    parser.add_argument("--hp-mode", choices=["off", "l1", "all"], default="off")
    parser.add_argument("--macro-depth", type=int, default=0)
    parser.add_argument("--macro-targets", type=int, default=0)
    parser.add_argument("--macro-soft-steps", type=int, default=1)
    parser.add_argument("--macro-budget-ms", type=float, default=0.0)
    parser.add_argument("--macro-enabled", action="store_true", help="Enable macro ordering.")
    parser.add_argument("--results-db", type=Path, default=Path("solver_results.sqlite"))
    parser.add_argument("--engine", choices=["v9", "v10", "v7new", "cpp"], default="v9")
    parser.add_argument(
        "--cpp-binary",
        type=Path,
        default=ROOT / "cppsolver" / "build" / "cppsolver",
        help="Path to the compiled C++ solver binary.",
    )
    parser.add_argument(
        "--cpp-bench-binary",
        type=Path,
        default=ROOT / "cppsolver_bench" / "build" / "cppsolver",
        help="Path to the benchmark C++ solver.",
    )
    parser.add_argument(
        "--cpp-mode",
        choices=["normal", "benchmark"],
        default="normal",
        help="Use benchmark mode for --engine cpp (no per-puzzle output).",
    )
    parser.add_argument("--single-wave-cap", type=int, default=SINGLE_WAVE_CAP)
    parser.add_argument("--k-cand", type=int, default=K_CAND)
    parser.add_argument("--use-l2", action="store_true")
    parser.add_argument("--l2-budget-node", type=int, default=0)
    parser.add_argument("--l2-budget-puzzle", type=int, default=0)
    parser.add_argument("--v7-profile-core", action="store_true")
    parser.add_argument("--v7-timeout", type=float, default=None)
    args = parser.parse_args()

    puzzles = _load_puzzles(args.puzzle, args.puzzle_file)
    if args.start < 0 or args.start >= len(puzzles):
        parser.error("Invalid --start index.")
    selected = puzzles[args.start :]
    if args.count is not None:
        selected = selected[: args.count]
    if not selected:
        parser.error("No puzzles in selected range.")
    puzzle_total = len(selected)

    dataset_label = str(args.puzzle_file or "inline_puzzle")
    script_name = {
        "v9": "v9_core",
        "v10": "v10_core",
        "v7new": "v7_core",
        "cpp": "cppsolver",
    }[args.engine]
    print(f"Start: *******{script_name} - {dataset_label} ******")

    use_np = args.rules_profile in {"pairs", "full"}
    use_hp = args.rules_profile == "full"
    rules = Rules(
        use_np=use_np,
        use_hp=use_hp,
        use_locks=args.locks_mode != "off",
        hp_mode=args.hp_mode,
        locks_mode=args.locks_mode,
    )
    macro_cfg = MacroConfig(
        enabled=args.macro_enabled,
        max_depth=max(0, args.macro_depth),
        targets=args.macro_targets,
        soft_steps=args.macro_soft_steps,
        budget_ms=args.macro_budget_ms,
    )
    v10_cfg = V10Config(
        single_wave_cap=max(1, args.single_wave_cap),
        k_cand=max(1, args.k_cand),
        use_l2=args.use_l2,
        l2_budget_node=max(0, args.l2_budget_node),
        l2_budget_puzzle=max(0, args.l2_budget_puzzle),
    )
    v7_cfg = V7NewConfig(
        profile_core=args.v7_profile_core,
        timeout=args.v7_timeout,
    )

    if args.engine == "cpp":
        if not args.puzzle_file:
            parser.error("--engine cpp requires --puzzle-file")
        binary = args.cpp_bench_binary if args.cpp_mode == "benchmark" else args.cpp_binary
        result = solve_dataset_cpp(args.puzzle_file, binary, args.cpp_mode == "benchmark")
        if args.cpp_mode == "benchmark":
            summary = result["stats_dict"].get("summary", "")
            print(summary)
        else:
            solved = len(result["solutions"])
            print(
                f"cppsolver finished returncode={result['stats_dict']['returncode']} "
                f"time={result['solve_time_ms']:.2f}ms "
                f"solutions={solved}"
            )
        solve_sec = result["solve_time_ms"] / 1000.0
        puzzles_per_sec = (puzzle_total / solve_sec) if solve_sec > 0 else 0.0
        status = "100.0% solved | " if result["success"] else ""
        print(
            f"End: ***************{script_name} - {dataset_label}. "
            f"{status}{puzzles_per_sec:.2f} puzzles/s - Total Solve Time {solve_sec:.2f} s ******"
        )
        return

    total_runs = 0
    solved_runs = 0
    per_run_ms: List[float] = []
    sum_solve_ms = 0.0
    overall_start = perf_counter()
    db_records: List[dict] = []

    for rep in range(args.timing_reps):
        order = list(enumerate(selected, start=args.start))
        if args.timing_reps > 1:
            rnd = random.Random(args.shuffle_seed + rep)
            rnd.shuffle(order)
        for puzzle_index, puzzle in order:
            for run in range(args.runs):
                total_runs += 1
                if args.engine == "v9":
                    result = solve_once_v9(puzzle, rules, macro_cfg)
                elif args.engine == "v10":
                    result = solve_once_v10(puzzle, v10_cfg)
                elif args.engine == "v7new":
                    result = solve_once_v7new(puzzle, v7_cfg)
                else:
                    result = solve_once_cpp(puzzle, args.cpp_binary)
                total_ms = result["s0_time_ms"] + result["solve_time_ms"]
                per_run_ms.append(total_ms)
                sum_solve_ms += result["solve_time_ms"]
                if result["success"]:
                    solved_runs += 1
                if not args.quiet:
                    if args.engine == "v9":
                        print(
                            f"[p{puzzle_index} rep {rep+1} run {run+1}] "
                            f"{'OK' if result['success'] else 'FAIL'} "
                            f"s0={result['s0_time_ms']:.2f}ms "
                            f"solve={result['solve_time_ms']:.2f}ms "
                            f"nodes={result['stats'].dfs_nodes} "
                            f"macro_sims={result['stats'].macro_sims}"
                        )
                    elif args.engine == "v10":
                        stats = result["stats_dict"]
                        print(
                            f"[p{puzzle_index} rep {rep+1} run {run+1}] "
                            f"{'OK' if result['success'] else 'FAIL'} "
                            f"s0={result['s0_time_ms']:.2f}ms "
                            f"solve={result['solve_time_ms']:.2f}ms "
                            f"nodes={stats['nodes']} "
                            f"depth={stats['max_depth']} "
                            f"ns={stats['ns_events']} "
                            f"hs={stats['hs_events']} "
                            f"l2={stats['l2_uses']}"
                        )
                    elif args.engine == "v7new":
                        stats = result["stats_dict"]
                        print(
                            f"[p{puzzle_index} rep {rep+1} run {run+1}] "
                            f"{'OK' if result['success'] else 'FAIL'} "
                            f"s0={result['s0_time_ms']:.2f}ms "
                            f"solve={result['solve_time_ms']:.2f}ms "
                            f"nodes={stats['nodes']} placements={stats['placements']}"
                        )
                    else:
                        print(
                            f"[p{puzzle_index} rep {rep+1} run {run+1}] "
                            f"{'OK' if result['success'] else 'FAIL'} "
                            f"solve={result['solve_time_ms']:.2f}ms "
                            f"binary={args.cpp_binary}"
                        )
                db_records.append(
                    {
                        "index": puzzle_index,
                        "status": "OK" if result["success"] else "FAIL",
                        "time_ms": total_ms,
                        "stats": (
                            {
                                "nodes": result["stats"].dfs_nodes,
                                "ns": result["stats"].ns_count,
                                "hs": result["stats"].hs_count,
                            }
                            if args.engine == "v9"
                            else result["stats_dict"]
                        ),
                        "puzzle": puzzle,
                        "solution": result.get("board") or result.get("solution"),
                        "verified": result["success"],
                        "error": None if result["success"] else "unsolved",
                        "rep_count": 1,
                        "solved_runs": 1 if result["success"] else 0,
                        "median_ms": total_ms,
                        "min_ms": total_ms,
                        "max_ms": total_ms,
                    }
                )

    total_elapsed = perf_counter() - overall_start
    if per_run_ms:
        mean_ms = sum(per_run_ms) / len(per_run_ms)
        med_ms = median(per_run_ms)
        print(
            f"Solved {solved_runs}/{total_runs} runs. "
            f"mean={mean_ms:.2f} ms, median={med_ms:.2f} ms, "
            f"wall={(total_elapsed*1000):.2f} ms."
        )
    total_solve_s = sum_solve_ms / 1000.0 if total_runs else 0.0
    puzzles_per_sec = (total_runs / total_solve_s) if total_solve_s > 0 else 0.0
    solved_pct = (solved_runs / total_runs * 100.0) if total_runs else 0.0

    if db_records:
        command_line = shlex.join(sys.argv)
        run_type = "timing" if args.timing_reps > 1 else "solve"
        with SolverDatabase(args.results_db) as db:
            recorded = db.record_run(
                script_name="planrun.py",
                command_line=command_line,
                dataset=dataset_label,
                args=args,
                run_records=db_records,
                html_report=None,
                run_type=run_type,
                timing_reps=args.timing_reps,
                total_time_ms=sum(per_run_ms),
            )
        print(f"Run recorded in {args.results_db} (run_id={recorded.run_id}).")

    print(
        f"End: ***************{script_name} - {dataset_label}. "
        f"{solved_pct:.1f}% solved | {puzzles_per_sec:.2f} puzzles/s - "
        f"Total Solve Time {total_solve_s:.2f} s ******"
    )


if __name__ == "__main__":
    main()
