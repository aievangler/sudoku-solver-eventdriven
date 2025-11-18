"""
Phase 0 scaffolding for the v10 solver.

This module defines static geometry, low-level utilities, and the bare State
container with trail/undo support. No solving logic appears here; later phases
layer elimination, placement, propagation, and DFS on top.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

CELLS: range = range(81)
DIGITS: range = range(9)
BIT81: List[int] = [1 << c for c in CELLS]

ROW_OF: List[int] = [c // 9 for c in CELLS]
COL_OF: List[int] = [c % 9 for c in CELLS]
BOX_OF: List[int] = [(ROW_OF[c] // 3) * 3 + (COL_OF[c] // 3) for c in CELLS]

UNIT_ROW: List[int] = list(range(9))
UNIT_COL: List[int] = [9 + c for c in range(9)]
UNIT_BOX: List[int] = [18 + b for b in range(9)]

UNIT_CELLS: List[List[int]] = []
# Rows
UNIT_CELLS.extend([[r * 9 + c for c in range(9)] for r in range(9)])
# Cols
UNIT_CELLS.extend([[r * 9 + c for r in range(9)] for c in range(9)])
# Boxes
for br in range(3):
    for bc in range(3):
        cells = []
        for dr in range(3):
            for dc in range(3):
                r = br * 3 + dr
                c = bc * 3 + dc
                cells.append(r * 9 + c)
        UNIT_CELLS.append(cells)

UNIT_MASK: List[int] = []
for unit in UNIT_CELLS:
    mask = 0
    for c in unit:
        mask |= BIT81[c]
    UNIT_MASK.append(mask)

PEER_MASKS: List[int] = []
for c in CELLS:
    mask = 0
    for p in UNIT_CELLS[ROW_OF[c]]:
        mask |= BIT81[p]
    for p in UNIT_CELLS[9 + COL_OF[c]]:
        mask |= BIT81[p]
    for p in UNIT_CELLS[18 + BOX_OF[c]]:
        mask |= BIT81[p]
    mask &= ~BIT81[c]
    PEER_MASKS.append(mask)

UNIT_OF_CELL: List[Tuple[int, int, int]] = [
    (UNIT_ROW[ROW_OF[c]], UNIT_COL[COL_OF[c]], UNIT_BOX[BOX_OF[c]]) for c in CELLS
]


# ---------------------------------------------------------------------------
# Heuristic constants
# ---------------------------------------------------------------------------

K_CAND = 2
GLOBAL_SCARCITY_WEIGHT = 1
SINGLE_WAVE_CAP = 32
WAVE_WEIGHT = 8
L2_WEIGHT = 4
L2_CONTRADICTION_BONUS = 64
VERY_BAD_SCORE = -10_000
HEUR_A = 5
HEUR_B = 3


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def popcount(x: int) -> int:
    """Bit population count wrapper."""
    return x.bit_count()


def ls1b_index(mask: int) -> int:
    """Return index of least-significant 1-bit. Undefined for mask==0."""
    return (mask & -mask).bit_length() - 1


PEERS: List[List[int]] = []
for c in CELLS:
    peers: List[int] = []
    mask = PEER_MASKS[c]
    while mask:
        p = ls1b_index(mask)
        peers.append(p)
        mask &= mask - 1
    PEERS.append(peers)


# ---------------------------------------------------------------------------
# State container and trail
# ---------------------------------------------------------------------------

TrailEntry = Tuple[str, int, int]


@dataclass
class State:
    B: List[int]
    cell_mask: List[int]
    deg: List[int]
    unitdigitcount: List[List[int]]
    value: List[int]
    digit_count: List[int]
    total_candidates: int
    unsolved_count: int

    NS_queue: List[int]
    HS_queue: List[Tuple[int, int]]

    contradiction: bool
    ns_events: int
    hs_events: int

    trail: List[TrailEntry]


@dataclass
class DFSStats:
    nodes: int = 0
    placements: int = 0
    max_depth: int = 0
    ns_events: int = 0
    hs_events: int = 0
    l2_uses: int = 0


@dataclass
class L2Tracker:
    remaining: int


def init_blank_state() -> State:
    """Return a fresh state with all candidates allowed."""
    B = [(1 << 81) - 1 for _ in DIGITS]
    cell_mask = [(1 << 9) - 1 for _ in CELLS]
    deg = [9 for _ in CELLS]
    unitdigitcount = [[9 for _ in DIGITS] for _ in range(27)]
    value = [-1 for _ in CELLS]
    digit_count = [81 for _ in DIGITS]
    total_candidates = 81 * 9
    unsolved_count = 81

    return State(
        B=B,
        cell_mask=cell_mask,
        deg=deg,
        unitdigitcount=unitdigitcount,
        value=value,
        digit_count=digit_count,
        total_candidates=total_candidates,
        unsolved_count=unsolved_count,
        NS_queue=[],
        HS_queue=[],
        contradiction=False,
        ns_events=0,
        hs_events=0,
        trail=[],
    )


def trail_mark(state: State) -> int:
    """Return current trail size for undo."""
    return len(state.trail)


def undo_to(state: State, mark: int) -> None:
    """Undo to the given trail mark."""
    while len(state.trail) > mark:
        tag, a, b = state.trail.pop()
        if tag == "ELIM":
            c = a
            d = b
            bit = BIT81[c]
            state.B[d] |= bit
            state.cell_mask[c] |= 1 << d
            state.deg[c] += 1
            state.total_candidates += 1
            r, col, box = UNIT_OF_CELL[c]
            state.unitdigitcount[r][d] += 1
            state.unitdigitcount[col][d] += 1
            state.unitdigitcount[box][d] += 1
            state.digit_count[d] += 1
        elif tag == "VAL":
            c = a
            old = b
            if state.value[c] != old:
                state.value[c] = old
            if old == -1:
                state.unsolved_count += 1
        else:  # pragma: no cover
            raise ValueError(f"Unknown trail tag {tag}")

    state.NS_queue.clear()
    state.HS_queue.clear()
    state.contradiction = False
    state.ns_events = 0
    state.hs_events = 0


# ---------------------------------------------------------------------------
# Core operations (Phase 1)
# ---------------------------------------------------------------------------

def eliminate(state: State, cell: int, digit: int) -> None:
    """Remove digit from cell, updating counts and queues."""
    bit = BIT81[cell]
    if not (state.B[digit] & bit):
        return

    state.trail.append(("ELIM", cell, digit))
    state.B[digit] &= ~bit
    state.cell_mask[cell] &= ~(1 << digit)
    state.deg[cell] -= 1
    state.total_candidates -= 1
    state.digit_count[digit] -= 1

    if state.deg[cell] == 0:
        state.contradiction = True

    if state.deg[cell] == 1:
        state.NS_queue.append(cell)

    u_row, u_col, u_box = UNIT_OF_CELL[cell]
    for u in (u_row, u_col, u_box):
        state.unitdigitcount[u][digit] -= 1
        cnt = state.unitdigitcount[u][digit]
        if cnt == 0:
            state.contradiction = True
        elif cnt == 1:
            state.HS_queue.append((u, digit))


def place_structural(state: State, cell: int, digit: int) -> None:
    """Fix cell to digit structurally (no DFS branching logic)."""
    current = state.value[cell]
    if current == digit:
        return
    if current != -1 and current != digit:
        state.contradiction = True
        return

    mask = state.cell_mask[cell] & ~(1 << digit)
    while mask:
        d2 = ls1b_index(mask)
        eliminate(state, cell, d2)
        if state.contradiction:
            return
        mask &= mask - 1

    bit = BIT81[cell]
    if not (state.B[digit] & bit):
        state.contradiction = True
        return

    peer_mask = state.B[digit] & PEER_MASKS[cell]
    while peer_mask:
        peer = ls1b_index(peer_mask)
        eliminate(state, peer, digit)
        if state.contradiction:
            return
        peer_mask &= peer_mask - 1

    state.trail.append(("VAL", cell, current))
    state.value[cell] = digit
    if current == -1:
        state.unsolved_count -= 1


def propagate_to_fixpoint(state: State) -> None:
    """Process NS/HS queues until empty or contradiction."""
    state.ns_events = 0
    state.hs_events = 0

    while (state.NS_queue or state.HS_queue) and not state.contradiction:
        if state.NS_queue:
            cell = state.NS_queue.pop()
            if state.value[cell] != -1 or state.deg[cell] != 1:
                continue
            mask = state.cell_mask[cell]
            if mask == 0:
                state.contradiction = True
                break
            if mask & (mask - 1):
                continue
            digit = ls1b_index(mask)
            state.ns_events += 1
            place_structural(state, cell, digit)
            continue

        unit, digit = state.HS_queue.pop()
        if state.unitdigitcount[unit][digit] != 1:
            continue
        mask = state.B[digit] & UNIT_MASK[unit]
        if mask == 0:
            state.contradiction = True
            break
        if mask & (mask - 1):
            continue
        cell = ls1b_index(mask)
        state.hs_events += 1
        place_structural(state, cell, digit)


# ---------------------------------------------------------------------------
# Phase 2: S0 build + minimal DFS
# ---------------------------------------------------------------------------

def build_S0(puzzle: str) -> State:
    """Build HS/NS fixpoint from givens, raising on contradiction."""
    state = init_blank_state()
    for idx, ch in enumerate(puzzle):
        if ch in ".0":
            continue
        if ch not in "123456789":
            raise ValueError(f"Invalid digit {ch!r}")
        digit = int(ch) - 1
        place_structural(state, idx, digit)
        if state.contradiction:
            raise ValueError("Contradiction while applying givens")
        propagate_to_fixpoint(state)
        if state.contradiction:
            raise ValueError("Contradiction after propagation of givens")
    return state


def first_unsolved_cell(state: State) -> Optional[int]:
    for c in CELLS:
        if state.value[c] == -1 and state.deg[c] > 0:
            return c
    return None


def digits_in_cell(state: State, cell: int) -> List[int]:
    mask = state.cell_mask[cell]
    digits = []
    while mask:
        digit = ls1b_index(mask)
        digits.append(digit)
        mask &= mask - 1
    return digits


def is_solved(state: State) -> bool:
    return state.unsolved_count == 0 and not state.contradiction


def solve_basic(state: State) -> bool:
    """Naive DFS with first-unsolved-cell selection."""
    propagate_to_fixpoint(state)
    if state.contradiction:
        return False
    if is_solved(state):
        return True

    cell = first_unsolved_cell(state)
    if cell is None:
        return False
    for digit in digits_in_cell(state, cell):
        mark = trail_mark(state)
        place_structural(state, cell, digit)
        if not state.contradiction:
            if solve_basic(state):
                return True
        undo_to(state, mark)
    return False


# ---------------------------------------------------------------------------
# Phase 3: MRV frontier + scoring + single-wave overlay
# ---------------------------------------------------------------------------

def _base_score(state: State, cell: int, digit: int) -> int:
    """Cheap locality-aware score for placing digit in cell."""
    row_unit, col_unit, box_unit = UNIT_OF_CELL[cell]
    unit_counts = state.unitdigitcount
    r = unit_counts[row_unit][digit]
    c = unit_counts[col_unit][digit]
    b = unit_counts[box_unit][digit]
    global_left = state.digit_count[digit]
    local_pressure = (9 - r) + (9 - c) + (9 - b)
    scarcity = GLOBAL_SCARCITY_WEIGHT * (81 - global_left)
    return local_pressure + scarcity


def single_wave_score_static(state: State, cell: int, digit: int) -> int:
    """Cheap v7-style heuristic: peek at consequences without mutations."""
    pred_cells = 0
    pred_units = 0

    bitmask_digit = state.B[digit]
    for peer in PEERS[cell]:
        peer_bit = BIT81[peer]
        if not (bitmask_digit & peer_bit):
            continue
        deg_peer = state.deg[peer]
        if deg_peer <= 1:
            return VERY_BAD_SCORE
        if deg_peer == 2:
            pred_cells += 1
        u_r, u_c, u_b = UNIT_OF_CELL[peer]
        for unit in (u_r, u_c, u_b):
            udeg = state.unitdigitcount[unit][digit]
            if udeg <= 1:
                return VERY_BAD_SCORE
            if udeg == 2:
                pred_units += 1

    u_r, u_c, u_b = UNIT_OF_CELL[cell]
    mask = state.cell_mask[cell]
    for unit in (u_r, u_c, u_b):
        for other_digit in DIGITS:
            if other_digit == digit:
                continue
            if not (mask & (1 << other_digit)):
                continue
            udeg = state.unitdigitcount[unit][other_digit]
            if udeg <= 1:
                return VERY_BAD_SCORE
            if udeg == 2:
                pred_units += 1

    return HEUR_A * pred_cells + HEUR_B * pred_units


def single_wave_score_dynamic(state: State, cell: int, digit: int, max_events: int = SINGLE_WAVE_CAP) -> int:
    """Simulate a bounded HS/NS wave after tentatively placing (cell,digit)."""
    if max_events <= 0:
        return 0

    saved_ns_queue = list(state.NS_queue)
    saved_hs_queue = list(state.HS_queue)
    saved_ns_events = state.ns_events
    saved_hs_events = state.hs_events
    saved_contradiction = state.contradiction

    state.NS_queue.clear()
    state.HS_queue.clear()

    mark = trail_mark(state)
    place_structural(state, cell, digit)

    events = 0
    while (state.NS_queue or state.HS_queue) and events < max_events and not state.contradiction:
        if state.NS_queue:
            nxt = state.NS_queue.pop()
            if state.value[nxt] != -1 or state.deg[nxt] != 1:
                continue
            mask = state.cell_mask[nxt]
            if mask == 0:
                state.contradiction = True
                break
            if mask & (mask - 1):
                continue
            inferred_digit = ls1b_index(mask)
            events += 1
            place_structural(state, nxt, inferred_digit)
            continue

        unit, hid_digit = state.HS_queue.pop()
        if state.unitdigitcount[unit][hid_digit] != 1:
            continue
        mask = state.B[hid_digit] & UNIT_MASK[unit]
        if mask == 0:
            state.contradiction = True
            break
        if mask & (mask - 1):
            continue
        inferred_cell = ls1b_index(mask)
        events += 1
        place_structural(state, inferred_cell, hid_digit)

    contradiction_seen = state.contradiction
    undo_to(state, mark)
    state.NS_queue.extend(saved_ns_queue)
    state.HS_queue.extend(saved_hs_queue)
    state.ns_events = saved_ns_events
    state.hs_events = saved_hs_events
    state.contradiction = saved_contradiction

    if contradiction_seen:
        return max_events + events + 1
    return events


def l2_local_score(state: State, cell: int, digit: int) -> int:
    """Local elimination-only probe around (cell, digit)."""
    saved_ns_queue = list(state.NS_queue)
    saved_hs_queue = list(state.HS_queue)
    saved_ns_events = state.ns_events
    saved_hs_events = state.hs_events
    saved_contradiction = state.contradiction
    saved_total = state.total_candidates

    state.NS_queue.clear()
    state.HS_queue.clear()

    mark = trail_mark(state)
    place_structural(state, cell, digit)

    delta = saved_total - state.total_candidates
    contradiction_seen = state.contradiction

    undo_to(state, mark)
    state.NS_queue.extend(saved_ns_queue)
    state.HS_queue.extend(saved_hs_queue)
    state.ns_events = saved_ns_events
    state.hs_events = saved_hs_events
    state.contradiction = saved_contradiction

    if contradiction_seen:
        return delta + L2_CONTRADICTION_BONUS
    return delta


def pick_target_cell(state: State) -> Optional[int]:
    best_deg: Optional[int] = None
    best_cell: Optional[int] = None
    for cell in CELLS:
        if state.value[cell] != -1:
            continue
        deg = state.deg[cell]
        if deg <= 0:
            return None
        if best_deg is None or deg < best_deg:
            best_deg = deg
            best_cell = cell
    return best_cell


def score_digits_for_cell(state: State, cell: int, k_candidates: int) -> List[Tuple[int, int]]:
    mask = state.cell_mask[cell]
    if mask == 0:
        return []
    local_scores: List[Tuple[int, int]] = []
    temp_mask = mask
    while temp_mask:
        digit = ls1b_index(temp_mask)
        base = _base_score(state, cell, digit)
        local_scores.append((base, digit))
        temp_mask &= temp_mask - 1
    local_scores.sort(reverse=True)

    ranked: List[Tuple[int, int]] = []
    for idx, (base, digit) in enumerate(local_scores):
        if k_candidates > 0 and idx < k_candidates:
            wave = single_wave_score_static(state, cell, digit)
            total = base + WAVE_WEIGHT * wave
        else:
            total = base
        ranked.append((total, digit))
    ranked.sort(reverse=True)
    return ranked


def choose_next(
    state: State,
    *,
    depth: int,
    k_candidates: int = K_CAND,
    use_l2: bool = False,
    l2_node_budget: int = 0,
    l2_puzzle_budget: int = 0,
) -> Optional[Tuple[int, List[int], int]]:
    cell = pick_target_cell(state)
    if cell is None:
        return None

    digits_scored = score_digits_for_cell(state, cell, k_candidates)
    if not digits_scored:
        return None

    digits_ordered = [digit for _, digit in digits_scored]
    l2_used = 0
    if use_l2 and digits_ordered:
        node_quota = max(0, min(l2_node_budget, l2_puzzle_budget))
        if node_quota > 0:
            scored: List[Tuple[int, int]] = []
            for idx, digit in enumerate(digits_ordered):
                score = 0
                if idx < node_quota:
                    l2_gain = l2_local_score(state, cell, digit)
                    score += L2_WEIGHT * l2_gain
                    l2_used += 1
                scored.append((score, digit))
            scored.sort(reverse=True)
            digits_ordered = [digit for _, digit in scored]

    return cell, digits_ordered, l2_used


def solve_v10(
    state: State,
    stats: Optional[DFSStats] = None,
    *,
    depth: int = 0,
    k_candidates: int = K_CAND,
    use_l2: bool = False,
    l2_budget_node: int = 0,
    l2_budget_puzzle: int = 0,
    l2_tracker: Optional[L2Tracker] = None,
) -> bool:
    """DFS with MRV + scoring + single-wave ordering."""
    if use_l2 and l2_tracker is None:
        l2_tracker = L2Tracker(max(0, l2_budget_puzzle))

    if stats is not None:
        stats.nodes += 1
        if depth > stats.max_depth:
            stats.max_depth = depth

    propagate_to_fixpoint(state)
    if stats is not None:
        stats.ns_events += state.ns_events
        stats.hs_events += state.hs_events

    if state.contradiction:
        return False
    if is_solved(state):
        return True

    current_l2_remaining = l2_tracker.remaining if (use_l2 and l2_tracker) else 0
    choice = choose_next(
        state,
        depth=depth,
        k_candidates=k_candidates,
        use_l2=use_l2 and current_l2_remaining > 0,
        l2_node_budget=l2_budget_node,
        l2_puzzle_budget=current_l2_remaining,
    )
    if not choice:
        return False
    cell, digits, used_l2 = choice
    if use_l2 and l2_tracker is not None:
        l2_tracker.remaining = max(0, l2_tracker.remaining - used_l2)
        if stats is not None and used_l2:
            stats.l2_uses += used_l2
    for digit in digits:
        mark = trail_mark(state)
        place_structural(state, cell, digit)
        if stats is not None and not state.contradiction:
            stats.placements += 1
        if not state.contradiction and solve_v10(
            state,
            stats,
            depth=depth + 1,
            k_candidates=k_candidates,
            use_l2=use_l2,
            l2_budget_node=l2_budget_node,
            l2_budget_puzzle=l2_budget_puzzle,
            l2_tracker=l2_tracker,
        ):
            return True
        undo_to(state, mark)
    return False


def solve_puzzle_v10(
    puzzle: str,
    *,
    max_events: int = SINGLE_WAVE_CAP,
    k_candidates: int = K_CAND,
    use_l2: bool = False,
    l2_budget_node: int = 0,
    l2_budget_puzzle: int = 0,
) -> Tuple[Optional[str], DFSStats]:
    """Convenience entry point: build S0, run DFS, return solution + stats."""
    state = build_S0(puzzle)
    stats = DFSStats()
    solved = solve_v10(
        state,
        stats,
        depth=0,
        max_events=max_events,
        k_candidates=k_candidates,
        use_l2=use_l2,
        l2_budget_node=l2_budget_node,
        l2_budget_puzzle=l2_budget_puzzle,
    )
    if not solved:
        return None, stats
    solution = ["." for _ in CELLS]
    for idx, digit in enumerate(state.value):
        if digit == -1:
            return None, stats
        solution[idx] = str(digit + 1)
    return "".join(solution), stats
