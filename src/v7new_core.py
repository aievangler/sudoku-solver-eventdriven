"""
Core logic extracted from the legacy v7 solver for reuse by other modules.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

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
        return value.bit_count()

except AttributeError:

    def bitcount(value: int) -> int:
        return bin(value).count("1")


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

ROW_OF: List[int] = [idx // 9 for idx in CELLS]
COL_OF: List[int] = [idx % 9 for idx in CELLS]
BOX_OF: List[int] = [(idx // 27) * 3 + (idx % 9) // 3 for idx in CELLS]

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
# Config tuning (same defaults as the legacy solver)
# ---------------------------------------------------------------------------

HEUR_A = 3
HEUR_B = 2
K_CAND = 2
DUPLET_MAX = 3
OVERLAY_MIN_UNSOLVED = 20
OVERLAY_MIN_MRV = 3
OVERLAY_DISABLE_CALLS = 500
OVERLAY_MIN_HIT_RATIO = 0.05


# ---------------------------------------------------------------------------
# Solver state and stats
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
        "hp_queue",
        "hp_pending",
        "profile_core",
        "time_prop",
        "time_score",
        "_prop_depth",
        "_prop_start",
    )

    def __init__(self, profile_core: bool = False) -> None:
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
        self.hp_queue: deque[int] = deque()
        self.hp_pending: set[int] = set()
        self.profile_core: bool = profile_core
        self.time_prop: float = 0.0
        self.time_score: float = 0.0
        self._prop_depth: int = 0
        self._prop_start: float = 0.0

    def has_digit(self, d: int, c: int) -> bool:
        return bool(self.B[d] & BIT[c])

    def unsolved_count(self) -> int:
        return 81 - self.placed_count

    def reset_touched_units(self) -> None:
        self.touched_units_since_branch.clear()

    def _prop_timer_start(self) -> None:
        if not self.profile_core:
            return
        if self._prop_depth == 0:
            self._prop_start = perf_counter()
        self._prop_depth += 1

    def _prop_timer_end(self) -> None:
        if not self.profile_core:
            return
        self._prop_depth -= 1
        if self._prop_depth == 0:
            self.time_prop += perf_counter() - self._prop_start

    def _enqueue_hidden_pair_unit(self, unit: int) -> None:
        if unit in self.hp_pending:
            return
        self.hp_pending.add(unit)
        self.hp_queue.append(unit)

    def _apply_clear(
        self,
        d: int,
        c: int,
        bit_flag: int,
        mark: int,
        update_board: bool,
    ) -> bool:
        timed = self.profile_core
        if timed:
            self._prop_timer_start()
        try:
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
                old = unit_digit_deg[unit][d]
                new = old - 1
                unit_digit_deg[unit][d] = new
                if new < 0:
                    self.undo_to(mark)
                    return False
                if new == 1:
                    self.Qunit.append((unit, d))
                if old != 2 and new == 2:
                    self._enqueue_hidden_pair_unit(unit)
                touched_units.add(unit)
            if cell_deg[c] == 0 and value[c] == -1:
                self.undo_to(mark)
                return False
            return True
        finally:
            if timed:
                self._prop_timer_end()

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
        timed = self.profile_core
        if timed:
            self._prop_timer_start()
        try:
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
        finally:
            if timed:
                self._prop_timer_end()

    def drain_events(self) -> bool:
        timed = self.profile_core
        if timed:
            self._prop_timer_start()
        try:
            Qcell = self.Qcell
            Qunit = self.Qunit
            value = self.value
            cell_deg = self.cell_deg
            unit_digit_deg = self.unit_digit_deg
            B = self.B
            while True:
                progressed = False
                while Qcell:
                    progressed = True
                    c = Qcell.popleft()
                    if value[c] != -1 or cell_deg[c] != 1:
                        continue
                    digit = self._single_digit(c)
                    if digit is None:
                        return False
                    if not self.place(c, digit):
                        return False
                while not Qcell and Qunit:
                    progressed = True
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
                if Qcell or Qunit:
                    continue
                if self.hp_queue:
                    progressed = True
                    unit = self.hp_queue.popleft()
                    self.hp_pending.discard(unit)
                    if not self._hidden_pairs_in_unit(unit):
                        return False
                    continue
                if not progressed:
                    return True
        finally:
            if timed:
                self._prop_timer_end()

    def _single_digit(self, c: int) -> Optional[int]:
        bit = BIT[c]
        B = self.B
        for d in DIGITS:
            if B[d] & bit:
                return d
        return None

    def _hidden_pairs_in_unit(self, unit: int) -> bool:
        unit_mask = UNIT_MASKS[unit]
        unit_degs = self.unit_digit_deg[unit]
        mask_to_digits: Dict[int, List[int]] = {}
        B = self.B
        for d in DIGITS:
            if unit_degs[d] == 2:
                mask = B[d] & unit_mask
                if bitcount(mask) == 2:
                    mask_to_digits.setdefault(mask, []).append(d)
        if not mask_to_digits:
            return True
        for mask, digits in mask_to_digits.items():
            if len(digits) != 2:
                continue
            allowed = set(digits)
            cells: List[int] = []
            temp = mask
            while temp:
                bit_flag = temp & -temp
                temp ^= bit_flag
                cells.append(_lsb_index(bit_flag))
            if len(cells) != 2:
                continue
            for c in cells:
                if self.value[c] != -1:
                    continue
                bit = BIT[c]
                for d in DIGITS:
                    if d in allowed:
                        continue
                    if B[d] & bit:
                        if not self.clear_bit(d, c):
                            return False
        return True

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
        self.hp_queue.clear()
        self.hp_pending.clear()

    def score_impact(self, c: int, d: int) -> int:
        local_tightness = max(0, 9 - self.cell_deg[c])
        peer_hits = bitcount(self.B[d] & PEER_MASKS[c])
        return local_tightness + peer_hits

    def first_wave_checks(self, c: int, d: int) -> Tuple[bool, int, int]:
        target_digit = d
        pred_cell = 0
        pred_unit = 0
        B = self.B
        cell_deg = self.cell_deg
        unit_digit_deg = self.unit_digit_deg
        bit_c = BIT[c]
        for t in PEERS[c]:
            if B[target_digit] & BIT[t]:
                deg = cell_deg[t]
                if deg == 1:
                    return False, 0, 0
                if deg == 2:
                    pred_cell += 1
                for unit in CELL_UNITS[t]:
                    udeg = unit_digit_deg[unit][target_digit]
                    if udeg == 1:
                        return False, 0, 0
                    if udeg == 2:
                        pred_unit += 1
        for unit in CELL_UNITS[c]:
            for e in DIGITS:
                if e == target_digit or not (B[e] & bit_c):
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
# Public API
# ---------------------------------------------------------------------------

def build_S0(puzzle: str, *, profile_core: bool = False) -> SolverState:
    """Initialize solver state from givens."""
    state = SolverState(profile_core=profile_core)
    for idx, ch in enumerate(puzzle):
        if ch in ".0":
            continue
        if ch not in "123456789":
            raise ValueError(f"Invalid digit '{ch}' in puzzle.")
        digit = int(ch) - 1
        if not state.try_place(idx, digit):
            raise ValueError("Contradiction while applying clues.")
    if not state.drain_events():
        raise ValueError("Contradiction after initial drain.")
    return state


def extract_solution(state: SolverState) -> Optional[str]:
    digits: List[str] = []
    for c in CELLS:
        d = state.value[c]
        if d == -1:
            return None
        digits.append(str(d + 1))
    return "".join(digits)


def solve_v7new(
    state: SolverState,
    stats: Optional[SolverStats] = None,
    *,
    timeout: Optional[float] = None,
) -> bool:
    """Run DFS using the legacy v7 heuristics."""
    working_stats = stats or SolverStats()
    deadline = (perf_counter() + timeout) if timeout else None

    def dfs() -> bool:
        if deadline is not None and perf_counter() > deadline:
            return False
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
                working_stats.nodes += 1
                if state.try_place(cell, overlay_opts[0]) and dfs():
                    return True
                state.undo_to(mark)
                state.reset_touched_units()
                state.overlay_disabled = True
                branch_digits = candidates[:]
            else:
                branch_digits = overlay_opts

        assert any(state.has_digit(d, cell) for d in DIGITS), "No live digits for branch cell"
        duplets = state.top_duplets()
        viable_duplets = [info for info in duplets if state.duplet_viable(info)]
        if len(viable_duplets) == 1:
            state.reset_touched_units()
            mark = len(state.trail)
            working_stats.nodes += 1
            if state.apply_duplet(viable_duplets[0]) and state.drain_events() and dfs():
                return True
            state.undo_to(mark)
            state.reset_touched_units()

        for d in branch_digits:
            if deadline is not None and perf_counter() > deadline:
                return False
            state.reset_touched_units()
            mark = len(state.trail)
            working_stats.nodes += 1
            if state.try_place(cell, d):
                working_stats.placements += 1
                if dfs():
                    return True
            state.undo_to(mark)
        return False

    return dfs()
