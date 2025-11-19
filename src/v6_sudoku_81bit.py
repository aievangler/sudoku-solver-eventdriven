"""
81x9 bitboard Sudoku solver with event-driven propagation, overlay gating,
and HTML reporting (microsecond-aware).
"""

from __future__ import annotations

__version__ = "0.1.0"
__author__ = "Bharat Mudholkar"
__license__ = "MIT"

import argparse
import json
import random
import shlex
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:  # Support both package (`python -m`) and script execution
    from .report_html import generate_html_report  # type: ignore[attr-defined]
    from .solver_db import SolverDatabase  # type: ignore[attr-defined]
except ImportError:
    from report_html import generate_html_report
    from solver_db import SolverDatabase

try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Geometry and helpers
# ---------------------------------------------------------------------------

DIGITS: range = range(9)
CELLS: range = range(81)
ALL_BITS: int = (1 << 81) - 1
BIT: List[int] = [1 << c for c in CELLS]

def _lsb_index(mask: int) -> int:
    return (mask & -mask).bit_length() - 1

try:
    _ = int.bit_count

    def bitcount(value: int) -> int:
        return value.bit_count()  # type: ignore[attr-defined]

except AttributeError:

    def bitcount(value: int) -> int:
        return bin(value).count("1")


def format_us(value: Any) -> str:
    return f"{value * 1000:.0f} \u00B5s" if isinstance(value, (int, float)) else "n/a"


def _with_run_id(path: Path, run_id: int) -> Path:
    stem = path.stem
    suffix = path.suffix
    return path.with_name(f"{stem}_run_{run_id}{suffix}")


ROWS: List[List[int]] = [[9 * r + c for c in range(9)] for r in range(9)]
COLS: List[List[int]] = [[9 * r + c for r in range(9)] for c in range(9)]
BOXES: List[List[int]] = []
for br in range(3):
    for bc in range(3):
        cells: List[int] = []
        for dr in range(3):
            for dc in range(3):
                cells.append((br * 3 + dr) * 9 + (bc * 3 + dc))
        BOXES.append(cells)

ROW_OF: List[int] = [0] * 81
COL_OF: List[int] = [0] * 81
BOX_OF: List[int] = [0] * 81
for idx in CELLS:
    ROW_OF[idx] = idx // 9
    COL_OF[idx] = idx % 9
    BOX_OF[idx] = (idx // 27) * 3 + (idx % 9) // 3

UNIT_CELLS: List[List[int]] = ROWS + COLS + BOXES  # 27 units
UNIT_MASKS: List[int] = [sum(BIT[c] for c in unit) for unit in UNIT_CELLS]

def unit_index_row(r: int) -> int:
    return r

def unit_index_col(c: int) -> int:
    return 9 + c

def unit_index_box(b: int) -> int:
    return 18 + b

ROW_UNIT: List[int] = [unit_index_row(ROW_OF[c]) for c in CELLS]
COL_UNIT: List[int] = [unit_index_col(COL_OF[c]) for c in CELLS]
BOX_UNIT: List[int] = [unit_index_box(BOX_OF[c]) for c in CELLS]
CELL_UNITS: List[Tuple[int, int, int]] = [
    (ROW_UNIT[c], COL_UNIT[c], BOX_UNIT[c]) for c in CELLS
]

PEER_MASKS: List[int] = [0] * 81
PEERS: List[List[int]] = [[] for _ in range(81)]
for c in CELLS:
    peers = set(ROWS[ROW_OF[c]] + COLS[COL_OF[c]] + BOXES[BOX_OF[c]])
    peers.discard(c)
    ordered = sorted(peers)
    mask = 0
    for t in ordered:
        mask |= BIT[t]
    PEER_MASKS[c] = mask
    PEERS[c] = ordered

# ---------------------------------------------------------------------------
# Config tuning
# ---------------------------------------------------------------------------

HEUR_A = 3
HEUR_B = 2
LOOKAHEAD_T = 1  # fixed at 1 (first-wave)
K_CAND = 2
DUPLET_MAX = 3
OVERLAY_MIN_UNSOLVED = 20
OVERLAY_MIN_MRV = 3
OVERLAY_DISABLE_CALLS = 500
OVERLAY_MIN_HIT_RATIO = 0.05

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _extract_puzzle(line: str) -> str:
    chars = [ch for ch in line if ch in "0123456789."]
    if len(chars) < 81:
        raise ValueError("Puzzle input must contain at least 81 digits/dots (.' or 0-9).")
    puzzle = "".join(chars[:81])
    if len(puzzle) != 81:
        raise ValueError("Puzzle input failed to produce exactly 81 characters.")
    return puzzle


def _load_puzzles(puzzle: Optional[str], puzzle_file: Optional[Path]) -> List[str]:
    puzzles: List[str] = []
    if puzzle:
        puzzles.append(_extract_puzzle(puzzle))
    if puzzle_file:
        lines = puzzle_file.read_text(encoding="utf-8").splitlines()
        for line_no, raw in enumerate(lines, start=1):
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                puzzles.append(_extract_puzzle(stripped))
            except ValueError as exc:
                raise ValueError(f"{puzzle_file}:{line_no}: {exc}") from exc
    return puzzles


def _verify_solution(puzzle: str, solution: Optional[str]) -> bool:
    if solution is None or len(solution) != 81:
        return False
    rows = [set() for _ in range(9)]
    cols = [set() for _ in range(9)]
    boxes = [set() for _ in range(9)]
    for idx, ch in enumerate(solution):
        if ch not in "123456789":
            return False
        r = idx // 9
        c = idx % 9
        b = (r // 3) * 3 + (c // 3)
        if ch in rows[r] or ch in cols[c] or ch in boxes[b]:
            return False
        rows[r].add(ch)
        cols[c].add(ch)
        boxes[b].add(ch)
    for idx, ch in enumerate(puzzle):
        if ch in "123456789" and solution[idx] != ch:
            return False
    return True

# ---------------------------------------------------------------------------
# Solver state
# ---------------------------------------------------------------------------

@dataclass
class SolverStats:
    nodes: int = 0
    placements: int = 0


class SolverState:
    __slots__ = (
        "B",
        "cell_deg",
        "unit_digit_deg",
        "value",
        "placed_count",
        "trail",
        "Qcell",
        "Qunit",
        "touched_units_since_branch",
        "overlay_calls",
        "overlay_rejects",
        "overlay_disabled",
    )

    def __init__(self) -> None:
        self.B: List[int] = [ALL_BITS for _ in DIGITS]
        self.cell_deg: List[int] = [9 for _ in CELLS]
        self.unit_digit_deg: List[List[int]] = [[9 for _ in DIGITS] for _ in range(27)]
        self.value: List[int] = [-1 for _ in CELLS]
        self.placed_count: int = 0
        self.trail: List[Tuple[str, int, Optional[int]]] = []
        self.Qcell: deque[int] = deque()
        self.Qunit: deque[Tuple[int, int]] = deque()
        self.touched_units_since_branch: set[int] = set()
        self.overlay_calls: int = 0
        self.overlay_rejects: int = 0
        self.overlay_disabled: bool = False

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------
    def has_digit(self, d: int, c: int) -> bool:
        return bool(self.B[d] & BIT[c])

    def unsolved_count(self) -> int:
        return 81 - self.placed_count

    def reset_touched_units(self) -> None:
        self.touched_units_since_branch.clear()

    def _apply_clear(
        self,
        d: int,
        c: int,
        bit_flag: int,
        mark: int,
        update_board: bool,
    ) -> bool:
        trail = self.trail
        if update_board:
            self.B[d] &= ~bit_flag
        trail.append(("CLR", c, d))
        cell_deg = self.cell_deg
        cell_deg[c] -= 1
        if cell_deg[c] < 0:
            self.undo_to(mark)
            return False
        value = self.value
        if value[c] == -1 and cell_deg[c] == 1:
            self.Qcell.append(c)
        touched_units = self.touched_units_since_branch
        unit_digit_deg = self.unit_digit_deg
        for unit in CELL_UNITS[c]:
            unit_digit_deg[unit][d] -= 1
            if unit_digit_deg[unit][d] < 0:
                self.undo_to(mark)
                return False
            if unit_digit_deg[unit][d] == 1:
                self.Qunit.append((unit, d))
            touched_units.add(unit)
        if cell_deg[c] == 0 and value[c] == -1:
            self.undo_to(mark)
            return False
        return True

    def clear_bit(self, d: int, c: int) -> bool:
        B = self.B
        value = self.value
        bit_flag = BIT[c]
        if not (B[d] & bit_flag):
            return True
        if value[c] == d:
            return False
        mark = len(self.trail)
        return self._apply_clear(d, c, bit_flag, mark, update_board=True)

    def place(self, c: int, d: int) -> bool:
        B = self.B
        bit = BIT[c]
        value = self.value
        if not (B[d] & bit):
            return False
        mark = len(self.trail)
        for e in DIGITS:
            if e != d and (B[e] & bit):
                if not self.clear_bit(e, c):
                    return False
        if value[c] == -1:
            value[c] = d
            self.placed_count += 1
            self.trail.append(("VAL", c, None))
        peer_mask = B[d] & PEER_MASKS[c]
        diff = peer_mask
        while diff:
            bit_flag = diff & -diff
            diff ^= bit_flag
            t = _lsb_index(bit_flag)
            if value[t] == d:
                self.undo_to(mark)
                return False
            if not self._apply_clear(d, t, bit_flag, mark, update_board=True):
                return False
        return True

    def drain_events(self) -> bool:
        Qcell = self.Qcell
        Qunit = self.Qunit
        value = self.value
        cell_deg = self.cell_deg
        unit_digit_deg = self.unit_digit_deg
        B = self.B
        while Qcell or Qunit:
            while Qcell:
                c = Qcell.popleft()
                if value[c] != -1 or cell_deg[c] != 1:
                    continue
                digit = self._single_digit(c)
                if digit is None:
                    return False
                if not self.place(c, digit):
                    return False
            while not Qcell and Qunit:
                unit, digit = Qunit.popleft()
                if unit_digit_deg[unit][digit] != 1:
                    continue
                mask = B[digit] & UNIT_MASKS[unit]
                if mask == 0:
                    return False
                c = _lsb_index(mask)
                if value[c] == -1:
                    if not self.place(c, digit):
                        return False
        return True

    def _single_digit(self, c: int) -> Optional[int]:
        bit = BIT[c]
        B = self.B
        for d in DIGITS:
            if B[d] & bit:
                return d
        return None

    def undo_to(self, mark: int) -> None:
        while len(self.trail) > mark:
            kind, c, payload = self.trail.pop()
            if kind == "CLR":
                if payload is None:
                    continue
                d = payload
                self.B[d] |= BIT[c]
                self.cell_deg[c] += 1
                row_unit, col_unit, box_unit = CELL_UNITS[c]
                self.unit_digit_deg[row_unit][d] += 1
                self.unit_digit_deg[col_unit][d] += 1
                self.unit_digit_deg[box_unit][d] += 1
            elif kind == "VAL":
                self.value[c] = -1
                self.placed_count -= 1
        self.Qcell.clear()
        self.Qunit.clear()

    # ------------------------------------------------------------------
    # Heuristics
    # ------------------------------------------------------------------
    def score_impact(self, c: int, d: int) -> int:
        return (self.cell_deg[c] - 1) + bitcount(self.B[d] & PEER_MASKS[c])

    def first_wave_checks(self, c: int, d: int) -> Tuple[bool, int, int]:
        pred_cell = 0
        pred_unit = 0
        B = self.B
        cell_deg = self.cell_deg
        unit_digit_deg = self.unit_digit_deg
        bit_c = BIT[c]
        for t in PEERS[c]:
            if B[d] & BIT[t]:
                deg = cell_deg[t]
                if deg == 1:
                    return False, 0, 0
                if deg == 2:
                    pred_cell += 1
                for unit in CELL_UNITS[t]:
                    udeg = unit_digit_deg[unit][d]
                    if udeg == 1:
                        return False, 0, 0
                    if udeg == 2:
                        pred_unit += 1
        for unit in CELL_UNITS[c]:
            for e in DIGITS:
                if e == d or not (B[e] & bit_c):
                    continue
                udeg = unit_digit_deg[unit][e]
                if udeg == 1:
                    return False, 0, 0
                if udeg == 2:
                    pred_unit += 1
        return True, pred_cell, pred_unit

    def score_move(self, c: int, d: int) -> int:
        ok, pc, pu = self.first_wave_checks(c, d)
        if not ok:
            return -10**9
        return self.score_impact(c, d) + HEUR_A * pc + HEUR_B * pu

    def choose_next(self) -> Optional[Tuple[int, List[int]]]:
        best_deg = None
        frontier: List[int] = []
        cell_deg = self.cell_deg
        for c in CELLS:
            if self.value[c] != -1:
                continue
            deg = cell_deg[c]
            if deg <= 0:
                return None
            if best_deg is None or deg < best_deg:
                best_deg = deg
                frontier = [c]
            elif deg == best_deg:
                frontier.append(c)
        if not frontier:
            return None
        best_cell = None
        best_list: List[Tuple[int, int]] = []
        best_score = -10**9
        B = self.B
        for c in frontier:
            bit = BIT[c]
            impacts = [(self.score_impact(c, d), d) for d in DIGITS if B[d] & bit]
            impacts.sort(reverse=True)
            local: List[Tuple[int, int]] = []
            for idx_imp, (impact, d) in enumerate(impacts):
                if idx_imp < K_CAND:
                    s = self.score_move(c, d)
                else:
                    s = impact
                local.append((s, d))
            local.sort(reverse=True)
            if local and local[0][0] > best_score:
                best_score = local[0][0]
                best_cell = c
                best_list = local
        if best_cell is None:
            return None
        return best_cell, [d for _, d in best_list]

    # ------------------------------------------------------------------
    # Overlay and duplets
    # ------------------------------------------------------------------
    def overlay_go_nogo(self, c: int, d: int) -> bool:
        self.overlay_calls += 1
        ok, _, _ = self.first_wave_checks(c, d)
        if not ok:
            self.overlay_rejects += 1
        if (
            self.overlay_calls >= OVERLAY_DISABLE_CALLS
            and (self.overlay_calls - self.overlay_rejects) / self.overlay_calls < OVERLAY_MIN_HIT_RATIO
        ):
            self.overlay_disabled = True
        return ok

    def top_duplets(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        B = self.B
        unit_digit_deg = self.unit_digit_deg
        for unit in list(self.touched_units_since_branch):
            cells = [c for c in UNIT_CELLS[unit] if self.value[c] == -1]
            if len(cells) < 2:
                continue
            mask_map: Dict[int, List[int]] = {}
            for c in cells:
                mask = 0
                for d in DIGITS:
                    if B[d] & BIT[c]:
                        mask |= 1 << d
                if bitcount(mask) == 2:
                    mask_map.setdefault(mask, []).append(c)
            for mask, positions in mask_map.items():
                if len(positions) != 2:
                    continue
                digits = [i for i in DIGITS if (mask >> i) & 1]
                impact = sum(unit_digit_deg[unit][d] - 2 for d in digits)
                if impact > 0:
                    results.append(
                        {
                            "kind": "naked",
                            "unit": unit,
                            "cells": tuple(positions),
                            "digits": tuple(digits),
                            "impact": impact,
                        }
                    )
            digit_cells: Dict[int, List[int]] = {}
            for d in DIGITS:
                if unit_digit_deg[unit][d] == 2:
                    positions = [c for c in cells if B[d] & BIT[c]]
                    if len(positions) == 2:
                        digit_cells[d] = positions
            pair_map: Dict[Tuple[int, int], List[int]] = {}
            for digit, positions in digit_cells.items():
                key = tuple(sorted(positions))
                pair_map.setdefault(key, []).append(digit)
            for (c1, c2), digits in pair_map.items():
                if len(digits) != 2:
                    continue
                p, q = sorted(digits)
                impact = (self.cell_deg[c1] - 2) + (self.cell_deg[c2] - 2)
                if impact > 0:
                    results.append(
                        {
                            "kind": "hidden",
                            "unit": unit,
                            "cells": (c1, c2),
                            "digits": (p, q),
                            "impact": impact,
                        }
                    )
        results.sort(key=lambda item: item["impact"], reverse=True)
        return results[:DUPLET_MAX]

    def apply_duplet(self, info: Dict[str, Any]) -> bool:
        kind = info["kind"]
        unit = info["unit"]
        cells = info["cells"]
        digits = info["digits"]
        B = self.B
        if kind == "naked":
            for c in UNIT_CELLS[unit]:
                if c in cells or self.value[c] != -1:
                    continue
                for d in digits:
                    if not self.clear_bit(d, c):
                        return False
        else:  # hidden pair
            allowed = set(digits)
            for c in cells:
                bit = BIT[c]
                for d in DIGITS:
                    if d not in allowed and (B[d] & bit):
                        if not self.clear_bit(d, c):
                            return False
        return True

    def duplet_viable(self, info: Dict[str, Any]) -> bool:
        snapshot = self.touched_units_since_branch.copy()
        mark = len(self.trail)
        ok = self.apply_duplet(info) and self.drain_events()
        self.undo_to(mark)
        self.touched_units_since_branch = snapshot
        return ok

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------
    def try_place(self, c: int, d: int) -> bool:
        mark = len(self.trail)
        if not self.place(c, d):
            self.undo_to(mark)
            return False
        if not self.drain_events():
            self.undo_to(mark)
            return False
        return True

# ---------------------------------------------------------------------------
# Solver driver
# ---------------------------------------------------------------------------

class Bit81Solver:
    def __init__(self, puzzle: str) -> None:
        self.state = SolverState()
        self.stats = SolverStats()
        for idx, ch in enumerate(puzzle):
            if ch in ".0":
                continue
            d = int(ch) - 1
            if d < 0 or d > 8:
                raise ValueError(f"Invalid digit '{ch}' in puzzle.")
            if not self.state.try_place(idx, d):
                raise ValueError("Contradiction while applying clues.")
        if not self.state.drain_events():
            raise ValueError("Contradiction after initial drain.")

    def solve(self) -> Optional[str]:
        if not self._dfs():
            return None
        digits = []
        for c in CELLS:
            d = self.state.value[c]
            if d == -1:
                return None
            digits.append(str(d + 1))
        return "".join(digits)

    def _dfs(self) -> bool:
        state = self.state
        if not state.drain_events():
            return False
        if state.placed_count == 81:
            return True
        choice = state.choose_next()
        if choice is None:
            return False
        cell, candidates = choice
        state.reset_touched_units()
        branch_digits = candidates[:]

        queues_empty = not state.Qcell and not state.Qunit
        if (
            queues_empty
            and not state.overlay_disabled
            and state.unsolved_count() >= OVERLAY_MIN_UNSOLVED
            and state.cell_deg[cell] >= OVERLAY_MIN_MRV
        ):
            overlay_opts = [d for d in branch_digits if state.overlay_go_nogo(cell, d)]
            if not overlay_opts:
                overlay_opts = branch_digits[:]
            if len(overlay_opts) == 1:
                state.reset_touched_units()
                mark = len(state.trail)
                self.stats.nodes += 1
                if state.try_place(cell, overlay_opts[0]) and self._dfs():
                    return True
                state.undo_to(mark)
                state.reset_touched_units()
                state.overlay_disabled = True
                branch_digits = candidates[:]
            else:
                branch_digits = overlay_opts

        assert any(self.state.has_digit(d, cell) for d in DIGITS), "No live digits for branch cell"
        duplets = state.top_duplets()
        viable_duplets = [info for info in duplets if state.duplet_viable(info)]
        if len(viable_duplets) == 1:
            state.reset_touched_units()
            mark = len(state.trail)
            self.stats.nodes += 1
            if state.apply_duplet(viable_duplets[0]) and state.drain_events() and self._dfs():
                return True
            state.undo_to(mark)
            state.reset_touched_units()

        for d in branch_digits:
            state.reset_touched_units()
            mark = len(state.trail)
            self.stats.nodes += 1
            if state.try_place(cell, d):
                self.stats.placements += 1
                if self._dfs():
                    return True
            state.undo_to(mark)
        return False


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _solve_single_attempt(puzzle: str, args: argparse.Namespace) -> Dict[str, Any]:
    best_time = None
    best_solution = None
    best_stats = None
    status = "FAIL"
    error_msg = None
    verified = False
    for _ in range(args.runs):
        try:
            solver = Bit81Solver(puzzle)
        except ValueError as exc:
            return {
                "time_ms": None,
                "stats": {"nodes": 0, "placements": 0},
                "solution": None,
                "verified": False,
                "status": "ERROR",
                "error": str(exc),
            }
        start = perf_counter()
        solution = solver.solve()
        elapsed_ms = (perf_counter() - start) * 1000.0
        stats_snapshot = {
            "nodes": solver.stats.nodes,
            "placements": solver.stats.placements,
        }
        if solution is not None:
            if best_time is None or elapsed_ms < best_time:
                best_time = elapsed_ms
                best_solution = solution
                best_stats = stats_snapshot
                verified = _verify_solution(puzzle, solution)
            status = "OK"
            error_msg = None
            break
        else:
            if best_stats is None:
                best_stats = stats_snapshot
            status = "FAIL"
            error_msg = "contradiction"
    return {
        "time_ms": best_time,
        "stats": best_stats or {"nodes": 0, "placements": 0},
        "solution": best_solution,
        "verified": verified,
        "status": status,
        "error": error_msg,
    }


def _print_single_result(idx: int, result: Dict[str, Any]) -> None:
    if result["status"] == "OK":
        ver_label = "verified" if result["verified"] else "UNVERIFIED"
        print(f"  Solution : {result['solution']} ({ver_label})")
    else:
        print("  No solution (contradiction detected)." if result["status"] == "FAIL" else f"  ERROR: {result['error']}")
    stats = result.get("stats") or {}
    print(f"  Stats    : nodes={stats.get('nodes', '—')} placements={stats.get('placements', '—')}")
    if result["time_ms"] is not None:
        print(f"  Time     : {result['time_ms']:.2f} ms ({format_us(result['time_ms'])})")


def _aggregate_puzzle_runs(
    index: int, puzzle: str, runs: List[Dict[str, Any]]
) -> Dict[str, Any]:
    rep_count = len(runs)
    solved_runs = sum(1 for r in runs if r["status"] == "OK" and r["time_ms"] is not None)
    solved_times = [r["time_ms"] for r in runs if r["time_ms"] is not None]
    median_ms = median(solved_times) if solved_times else 0.0
    min_ms = min(solved_times) if solved_times else 0.0
    max_ms = max(solved_times) if solved_times else 0.0
    mean_ms = (sum(solved_times) / len(solved_times)) if solved_times else 0.0
    nodes_values = [r["stats"]["nodes"] for r in runs if r["stats"]]
    placements_values = [r["stats"]["placements"] for r in runs if r["stats"]]
    nodes_mean = (sum(nodes_values) / len(nodes_values)) if nodes_values else 0.0
    placements_mean = (sum(placements_values) / len(placements_values)) if placements_values else 0.0
    if solved_runs == rep_count and rep_count > 0:
        status = "OK"
        error_msg = None
    elif solved_runs > 0:
        status = "PARTIAL"
        error_msg = "Some repetitions failed"
    else:
        status = runs[-1]["status"] if runs else "FAIL"
        error_msg = runs[-1]["error"] if runs else "unknown"
    solution = next((r["solution"] for r in runs if r["solution"]), None)
    verified_any = any(r.get("verified") for r in runs)
    return {
        "index": index,
        "puzzle": puzzle,
        "status": status,
        "solution": solution,
        "error": error_msg,
        "time_ms": mean_ms,
        "median_ms": median_ms,
        "min_ms": min_ms,
        "max_ms": max_ms,
        "rep_count": rep_count,
        "solved_runs": solved_runs,
        "stats": {"nodes": nodes_mean, "placements": placements_mean},
        "verified": verified_any,
    }


def _export_results_csv(path: Path, run_records: List[Dict[str, Any]]) -> None:
    header = [
        "index",
        "puzzle",
        "status",
        "mean_ms",
        "median_ms",
        "min_ms",
        "max_ms",
        "solved_runs",
        "rep_count",
        "nodes_mean",
        "placements_mean",
        "solution",
        "error",
    ]
    lines = [",".join(header)]
    for record in run_records:
        stats = record.get("stats") or {}
        row = [
            str(record.get("index")),
            record.get("puzzle", ""),
            record.get("status", ""),
            f"{record.get('time_ms', 0.0):.6f}",
            f"{record.get('median_ms', 0.0):.6f}",
            f"{record.get('min_ms', 0.0):.6f}",
            f"{record.get('max_ms', 0.0):.6f}",
            str(record.get("solved_runs", 1)),
            str(record.get("rep_count", 1)),
            f"{stats.get('nodes', 0.0):.6f}",
            f"{stats.get('placements', 0.0):.6f}",
            record.get("solution") or "",
            record.get("error") or "",
        ]
        lines.append(",".join(row))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="81x9 bitboard Sudoku solver.")
    parser.add_argument("puzzle", nargs="?", help="Single puzzle string (81 chars).")
    parser.add_argument(
        "--puzzle-file",
        type=Path,
        help="Path to a text file with one puzzle per line.",
    )
    parser.add_argument(
        "--start",
        type=int,
        default=0,
        help="0-based index of the first puzzle to solve.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Maximum number of puzzles to process.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of solve attempts per puzzle (timing repeats).",
    )
    parser.add_argument(
        "--timing-reps",
        type=int,
        default=1,
        help="Number of shuffled dataset repetitions for timing (paper-mode).",
    )
    parser.add_argument(
        "--shuffle-seed",
        type=int,
        default=1337,
        help="Base RNG seed used when timing reps > 1.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-puzzle console output.",
    )
    parser.add_argument(
        "--html-output",
        type=Path,
        default=None,
        help="Optional directory/file for HTML reports (with microsecond stats).",
    )
    parser.add_argument(
        "--results-db",
        type=Path,
        default=Path("solver_results.sqlite"),
        help="SQLite database that stores summarized run/puzzle metrics.",
    )
    parser.add_argument(
        "--export-csv",
        type=Path,
        help="Optional CSV path for exporting aggregated per-puzzle stats.",
    )
    parser.add_argument(
        "--export-meta",
        type=Path,
        help="Optional JSON metadata file describing the exported run.",
    )
    args = parser.parse_args(argv)
    try:
        puzzles = _load_puzzles(args.puzzle, args.puzzle_file)
    except ValueError as exc:
        parser.error(str(exc))
        return 1
    if not puzzles:
        parser.error("No puzzles supplied.")
        return 1
    if args.start < 0:
        parser.error("--start must be non-negative.")
    if args.count is not None and args.count <= 0:
        parser.error("--count must be positive when provided.")
    if args.runs <= 0:
        parser.error("--runs must be positive.")
    if args.timing_reps <= 0:
        parser.error("--timing-reps must be positive.")

    selected = puzzles[args.start :]
    if args.count is not None:
        selected = selected[: args.count]
    if not selected:
        print("No puzzles in requested slice.")
        return 0
    script_name = Path(sys.argv[0]).name
    command_line = " ".join([shlex.quote(sys.executable)] + [shlex.quote(arg) for arg in sys.argv])
    dataset_label = (
        str(args.puzzle_file)
        if args.puzzle_file
        else ("inline_puzzle" if args.puzzle else "N/A")
    )
    print(f"Start: *******{script_name} - {dataset_label} ******")
    overall_start = perf_counter()

    puzzle_runs: List[Dict[str, Any]] = [
        {"index": args.start + offset + 1, "puzzle": puzzle, "runs": []}
        for offset, puzzle in enumerate(selected)
    ]
    rng_seed = args.shuffle_seed
    for rep in range(args.timing_reps):
        order = list(range(len(puzzle_runs)))
        if args.timing_reps > 1:
            random.Random(rng_seed + rep).shuffle(order)
        for pos in order:
            entry = puzzle_runs[pos]
            if args.timing_reps == 1 and not args.quiet:
                print(f"Puzzle {entry['index']}: {entry['puzzle']}")
            result = _solve_single_attempt(entry["puzzle"], args)
            entry["runs"].append(result)
            if args.timing_reps == 1 and not args.quiet:
                _print_single_result(entry["index"], result)

    run_records: List[Dict[str, Any]] = []
    exit_code = 0
    verified_total = 0
    for entry in puzzle_runs:
        record = _aggregate_puzzle_runs(entry["index"], entry["puzzle"], entry["runs"])
        if record["status"] != "OK":
            exit_code = 1
        if record.get("verified"):
            verified_total += 1
        run_records.append(record)
        if args.timing_reps > 1 and not args.quiet:
            print(
                f"Puzzle {record['index']}: mean {record['time_ms']:.2f} ms "
                f"(median {record['median_ms']:.2f} ms) solved {record['solved_runs']}/{record['rep_count']}"
            )

    min_time = median_time = mean_time = max_time = 0.0
    aggregate_summary = None
    aggregate_summary_us = None
    if run_records:
        times = [
            rec["time_ms"] for rec in run_records if isinstance(rec.get("time_ms"), (int, float))
        ]
        if times:
            min_time = min(times)
            median_time = median(times)
            mean_time = mean(times)
            max_time = max(times)
            aggregate_summary = (
                "Aggregate timing (ms): "
                f"min {min_time:.2f} | median {median_time:.2f} | "
                f"mean {mean_time:.2f} | max {max_time:.2f}"
            )
            aggregate_summary_us = (
                "Aggregate timing (\u00B5s): "
                f"min {format_us(min_time)} | median {format_us(median_time)} | "
                f"mean {format_us(mean_time)} | max {format_us(max_time)}"
            )
            if median_time < 1.0:
                print("Performance note: microsecond regime detected — consider moving the core to C++.")
            elif median_time < 10.0:
                print("Performance note: single-digit millisecond regime — a tiny compiled core could help while keeping Python orchestration.")
        solved_count = sum(1 for rec in run_records if rec["status"] == "OK")
        solved_pct = (solved_count / len(run_records) * 100.0) if run_records else 0.0
        print(f"Solved {solved_count}/{len(run_records)} puzzle(s) ({solved_pct:.1f}%).")
        verified_run_count = sum(1 for rec in run_records if rec.get("verified"))
        verified_pct = (verified_run_count / len(run_records) * 100.0) if run_records else 0.0
        print(f"Verified {verified_run_count}/{len(run_records)} puzzle(s) ({verified_pct:.1f}%).")
    else:
        solved_count = verified_run_count = 0

    total_runtime_s = perf_counter() - overall_start
    divisor = len(run_records) * max(1, args.timing_reps)
    mean_runtime_ms = (total_runtime_s * 1000.0 / divisor) if divisor else 0.0
    print(
        f"Total runtime: {total_runtime_s:.2f} s | mean per puzzle: {mean_runtime_ms:.2f} ms"
    )

    run_type = "timing" if args.timing_reps > 1 else "solve"
    total_time_ms = total_runtime_s * 1000.0
    export_csv_path: Optional[Path] = None
    export_meta_path: Optional[Path] = None
    if args.export_csv:
        export_csv_path = args.export_csv
        _export_results_csv(export_csv_path, run_records)
    if args.export_meta:
        export_meta_path = args.export_meta
        meta_payload = {
            "script": script_name,
            "command": command_line,
            "dataset": dataset_label,
            "run_type": run_type,
            "timing_reps": args.timing_reps,
            "runs_per_puzzle": args.runs,
            "puzzles": len(run_records),
            "solved": solved_count if run_records else 0,
            "verified": verified_run_count if run_records else 0,
            "min_ms": min_time,
            "median_ms": median_time,
            "mean_ms": mean_time,
            "max_ms": max_time,
            "total_runtime_ms": total_time_ms,
        }
        export_meta_path.parent.mkdir(parents=True, exist_ok=True)
        export_meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")

    html_report_path: Optional[Path] = None
    recorded_run_id: Optional[int] = None
    with SolverDatabase(args.results_db) as db:
        recorded = db.record_run(
            script_name=script_name,
            command_line=command_line,
            dataset=dataset_label,
            args=args,
            run_records=run_records,
            html_report=None,
            run_type=run_type,
            timing_reps=args.timing_reps,
            total_time_ms=total_time_ms,
        )
        recorded_run_id = recorded.run_id
        if args.html_output:
            html_report_path = generate_html_report(
                args.html_output,
                args,
                run_records,
                script_name,
                command_line,
                format_us,
                db_run_id=recorded_run_id,
                total_time_ms=total_time_ms,
            )
            db.update_html_report(recorded_run_id, html_report_path)
    if recorded_run_id is not None:
        if export_csv_path:
            new_csv = _with_run_id(export_csv_path, recorded_run_id)
            export_csv_path.rename(new_csv)
            export_csv_path = new_csv
        if export_meta_path:
            new_meta = _with_run_id(export_meta_path, recorded_run_id)
            export_meta_path.rename(new_meta)
            export_meta_path = new_meta
        if html_report_path:
            new_html = _with_run_id(html_report_path, recorded_run_id)
            html_report_path.rename(new_html)
            html_report_path = new_html
    if export_csv_path:
        print(f"Per-puzzle stats exported to {export_csv_path}")
    if export_meta_path:
        print(f"Metadata written to {export_meta_path}")
    if html_report_path:
        print(f"\nHTML report written to {html_report_path}")
    if recorded_run_id is not None:
        print(f"Run recorded in {args.results_db} (run_id={recorded_run_id}).")
    if aggregate_summary:
        print(f"\n{aggregate_summary}")
    if aggregate_summary_us:
        print(aggregate_summary_us)
    if exit_code != 0:
        print("*** Run finished with failures. Check details above. ***", file=sys.stderr)
    solved_pct_final = (solved_count / len(run_records) * 100.0) if run_records else 0.0
    puzzles_per_sec = (len(run_records) / total_runtime_s) if total_runtime_s > 0 else 0.0
    sec_per_puzzle = (
        (total_runtime_s / len(run_records)) if run_records and total_runtime_s > 0 else 0.0
    )
    print(
        f"End: ***************{script_name} - {dataset_label}. "
        f"{solved_pct_final:.1f}% solved | {puzzles_per_sec:.2f} puzzles/s - "
        f"Total Time - {total_runtime_s:.2f} s Sec/puzzle: {sec_per_puzzle:.4f} ******"
    )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
