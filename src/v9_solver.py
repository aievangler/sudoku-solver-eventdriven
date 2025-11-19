"""V9 bitboard solver skeleton: phases 0-5 (S0..policy + macro bridge)."""
from __future__ import annotations

import argparse
import random
import math
import shlex
import sys
from pathlib import Path
from time import perf_counter
from dataclasses import dataclass
from statistics import mean, median
from typing import List, Optional

from solver_db import SolverDatabase

CELLS = range(81)
DIGITS = range(9)
BIT81: List[int] = [1 << c for c in CELLS]

ROW_OF = [c // 9 for c in CELLS]
COL_OF = [c % 9 for c in CELLS]
BOX_OF = [(r // 3) * 3 + (c // 3) for r, c in zip(ROW_OF, COL_OF)]
ROWS = [[9 * r + c for c in range(9)] for r in range(9)]
COLS = [[9 * r + c for r in range(9)] for c in range(9)]
BOXES = []
for br in range(3):
    for bc in range(3):
        BOXES.append([((br * 3 + dr) * 9 + (bc * 3 + dc)) for dr in range(3) for dc in range(3)])
UNIT_CELLS = ROWS + COLS + BOXES
CELL_UNITS = [
    (ROW_OF[c], 9 + COL_OF[c], 18 + BOX_OF[c]) for c in CELLS
]
UNIT_MASKS = [sum(BIT81[c] for c in unit) for unit in UNIT_CELLS]

PEERS_MASK = []
for c in CELLS:
    mask = 0
    for p in ROWS[ROW_OF[c]]:
        mask |= BIT81[p]
    for p in COLS[COL_OF[c]]:
        mask |= BIT81[p]
    for p in BOXES[BOX_OF[c]]:
        mask |= BIT81[p]
    mask &= ~BIT81[c]
    PEERS_MASK.append(mask)

STATUS_RANK = {"contradiction": 0, "solved": 1, "neutral": 2}


DEBUG = False

try:  # Python 3.11+
    int_bit_count = int.bit_count  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover
    def _popcount(x: int) -> int:
        return bin(x).count("1")
else:
    def _popcount(x: int) -> int:
        return int_bit_count(x)


def _state_hash(B: List[int]) -> int:
    return hash(tuple(B))


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    if pct <= 0:
        return min(values)
    if pct >= 1:
        return max(values)
    ordered = sorted(values)
    pos = pct * (len(ordered) - 1)
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[lower]
    frac = pos - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * frac


def _iter_bits(mask: int):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


@dataclass
class Rules:
    use_np: bool = False
    use_hp: bool = False
    use_locks: bool = True
    hp_mode: str = "off"
    locks_mode: str = "all"


@dataclass
class MacroConfig:
    mode: str = "off"
    targets: int = 0
    soft_passes: int = 0
    budget_ms: float = 0.0
    max_depth: int = 0


@dataclass
class SoftResult:
    cell: int
    digit: int
    status: str
    ns_gain: int
    cand_before: int
    cand_after: int
    passes: int


@dataclass
class MacroPlan:
    per_cell_order: dict[int, List[int]]
    results: List[SoftResult]
    stats: dict


def debug_assert_state(B: List[int]) -> None:
    if not DEBUG:
        return
    open_mask = 0
    for d in DIGITS:
        open_mask |= B[d]
    for c in CELLS:
        mask = cell_mask(B, c)
        assert mask != 0, f"Cell {c} empty"
        if _popcount(mask) == 1:
            d = (mask & -mask).bit_length() - 1
            assert (B[d] & PEERS_MASK[c]) == 0, f"Solved cell {c} conflicts peers"
    for unit_idx, unit_mask in enumerate(UNIT_MASKS):
        for d in DIGITS:
            assert (B[d] & unit_mask) != 0, f"Unit {unit_idx} digit {d} impossible"


def cell_mask(B: List[int], cell: int) -> int:
    mask = 0
    for d in DIGITS:
        if B[d] & BIT81[cell]:
            mask |= 1 << d
    return mask


def place_structural(B: List[int], cell: int, digit: int) -> bool:
    bit = BIT81[cell]
    if (B[digit] & bit) == 0:
        return False
    for d in DIGITS:
        if d == digit:
            continue
        B[d] &= ~bit
    B[digit] |= bit
    B[digit] &= ~PEERS_MASK[cell]
    B[digit] |= bit  # ensure the placed cell stays set
    return True


def clone_state(B: List[int]) -> List[int]:
    return [value for value in B]


def is_solved(B: List[int]) -> bool:
    for c in CELLS:
        mask = cell_mask(B, c)
        if mask == 0 or _popcount(mask) != 1:
            return False
    return True


def count_solved(B: List[int]) -> int:
    total = 0
    for c in CELLS:
        if _popcount(cell_mask(B, c)) == 1:
            total += 1
    return total


def total_candidates(B: List[int]) -> int:
    total = 0
    for c in CELLS:
        total += _popcount(cell_mask(B, c))
    return total


def has_candidate(B: List[int], cell: int, digit: int) -> bool:
    return (B[digit] & BIT81[cell]) != 0


def close_all(B: List[int], rules: Rules, max_passes: int | None = None) -> bool:
    ok, _ = _close_all(B, rules, max_passes)
    return ok


def _close_all(B: List[int], rules: Rules, max_passes: int | None) -> tuple[bool, int]:
    passes = 0
    while True:
        changed = False
        for c in CELLS:
            mask = cell_mask(B, c)
            if mask == 0:
                return False, passes
            if _popcount(mask) == 1:
                d = (mask & -mask).bit_length() - 1
                bit = BIT81[c]
                solved_here = all(((B[d2] & bit) == 0) for d2 in DIGITS if d2 != d)
                peers_clean = (B[d] & PEERS_MASK[c]) == 0
                if solved_here and peers_clean:
                    continue
                if not place_structural(B, c, d):
                    return False, passes
                changed = True
        for unit_idx, unit_cells in enumerate(UNIT_CELLS):
            unit_mask = UNIT_MASKS[unit_idx]
            for d in DIGITS:
                candidates = B[d] & unit_mask
                cnt = _popcount(candidates)
                if cnt == 0:
                    return False, passes
                if cnt == 1:
                    cell_bit = candidates & -candidates
                    cell = cell_bit.bit_length() - 1
                    bit = BIT81[cell]
                    solved_here = all(((B[d2] & bit) == 0) for d2 in DIGITS if d2 != d)
                    peers_clean = (B[d] & PEERS_MASK[cell]) == 0
                    if solved_here and peers_clean:
                        continue
                    if not place_structural(B, cell, d):
                        return False, passes
                    changed = True
        if rules.use_np:
            for unit_idx, unit_cells in enumerate(UNIT_CELLS):
                unit_mask = UNIT_MASKS[unit_idx]
                buckets: dict[int, List[int]] = {}
                for c in unit_cells:
                    mask = cell_mask(B, c)
                    if mask == 0:
                        return False, passes
                    if _popcount(mask) == 2:
                        buckets.setdefault(mask, []).append(c)
                for pair_mask, cells in buckets.items():
                    if len(cells) != 2:
                        continue
                    pair_bits = BIT81[cells[0]] | BIT81[cells[1]]
                    others = unit_mask & ~pair_bits
                    if others == 0:
                        continue
                    for d in _iter_bits(pair_mask):
                        before = B[d]
                        B[d] &= ~others
                        if B[d] != before:
                            changed = True
        if rules.use_hp:
            for unit_mask in UNIT_MASKS:
                occ = [B[d] & unit_mask for d in DIGITS]
                for d1 in range(8):
                    occ1 = occ[d1]
                    if _popcount(occ1) != 2:
                        continue
                    for d2 in range(d1 + 1, 9):
                        if occ1 != occ[d2]:
                            continue
                        cells_mask = occ1
                        keep_mask = (1 << d1) | (1 << d2)
                        cm = cells_mask
                        while cm:
                            bit = cm & -cm
                            cm ^= bit
                            cell = bit.bit_length() - 1
                            extras = cell_mask(B, cell) & ~keep_mask
                            if not extras:
                                continue
                            for dx in _iter_bits(extras):
                                bit_cell = BIT81[cell]
                                before = B[dx]
                                B[dx] &= ~bit_cell
                                if before != B[dx]:
                                    changed = True
        passes += 1
        if not changed:
            return True, passes
        if max_passes is not None and passes >= max_passes:
            return True, passes


def _board_counts(B: List[int]) -> List[int]:
    return [_popcount(B[d]) for d in DIGITS]


def _solved_mask(B: List[int]) -> int:
    solved = 0
    for c in CELLS:
        if _popcount(cell_mask(B, c)) == 1:
            solved |= BIT81[c]
    return solved


def choose_cell(B: List[int]) -> int:
    solved_mask = _solved_mask(B)
    board_counts = _board_counts(B)
    best_cell = -1
    best_key = None
    for c in CELLS:
        mask = cell_mask(B, c)
        pc = _popcount(mask)
        if pc <= 1:
            continue
        digits = list(_iter_bits(mask))
        peer_solved = _popcount(solved_mask & PEERS_MASK[c])
        scarcity = min(board_counts[d] for d in digits)
        unit_tension = min(
            _popcount(B[d] & UNIT_MASKS[u])
            for d in digits
            for u in CELL_UNITS[c]
        )
        key = (pc, scarcity, unit_tension, -peer_solved, c)
        if best_key is None or key < best_key:
            best_key = key
            best_cell = c
    return best_cell


def order_digits(B: List[int], cell: int) -> List[int]:
    mask = cell_mask(B, cell)
    digits = list(_iter_bits(mask))
    board_counts = _board_counts(B)
    def digit_key(d: int) -> tuple[int, int, int]:
        unit_min = min(_popcount(B[d] & UNIT_MASKS[u]) for u in CELL_UNITS[cell])
        return (board_counts[d], unit_min, d)
    digits.sort(key=digit_key)
    return digits


def soft_simulate_guess(
    B: List[int],
    cell: int,
    digit: int,
    rules: Rules,
    max_passes: int,
) -> SoftResult:
    base_solved = count_solved(B)
    base_cand = total_candidates(B)
    branch = clone_state(B)
    if not place_structural(branch, cell, digit):
        return SoftResult(cell, digit, "contradiction", 0, base_cand, base_cand, 0)
    ok, passes = _close_all(branch, rules, max_passes)
    if not ok:
        return SoftResult(cell, digit, "contradiction", 0, base_cand, base_cand, passes)
    ns_gain = max(0, count_solved(branch) - base_solved)
    cand_after = total_candidates(branch)
    status = "solved" if is_solved(branch) else "neutral"
    return SoftResult(cell, digit, status, ns_gain, base_cand, cand_after, passes)


def gather_macro_candidates(B: List[int], limit: int) -> List[tuple[int, int]]:
    if limit <= 0:
        return []
    solved_mask = _solved_mask(B)
    board_counts = _board_counts(B)
    scored: List[tuple[tuple[int, int, int, int, int], int]] = []
    for c in CELLS:
        mask = cell_mask(B, c)
        pc = _popcount(mask)
        if pc <= 1:
            continue
        digits = list(_iter_bits(mask))
        peer_solved = _popcount(solved_mask & PEERS_MASK[c])
        scarcity = min(board_counts[d] for d in digits)
        unit_tension = min(
            _popcount(B[d] & UNIT_MASKS[u])
            for d in digits
            for u in CELL_UNITS[c]
        )
        key = (pc, scarcity, unit_tension, -peer_solved, c)
        scored.append((key, c))
    scored.sort()
    moves: List[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for _, cell in scored:
        for digit in order_digits(B, cell):
            move = (cell, digit)
            if move in seen:
                continue
            seen.add(move)
            moves.append(move)
            if len(moves) >= limit:
                return moves
    return moves


def _should_commit(res: SoftResult, gain_min: int, ratio: float) -> bool:
    if res.status == "contradiction":
        return False
    if res.status == "solved":
        return True
    if res.ns_gain >= gain_min:
        return True
    if res.cand_before > 0 and res.cand_after <= ratio * res.cand_before:
        return True
    return False


def build_macro_plan(B: List[int], rules: Rules, cfg: MacroConfig) -> MacroPlan:
    stats: dict[str, object] = {
        "macro_mode": cfg.mode,
        "macro_sims": 0,
        "macro_bail_reason": "none",
        "macro_build_time_ms": 0.0,
        "macro_commits": 0,
        "macro_commit_type": "none",
        "macro_pairs_ranked": 0,
        "macro_pairs_validated": 0,
    }
    if cfg.mode == "off" or cfg.targets <= 0 or cfg.soft_passes <= 0:
        stats["macro_bail_reason"] = "off" if cfg.mode == "off" else "disabled"
        return MacroPlan({}, [], stats)
    candidates = gather_macro_candidates(B, cfg.targets)
    if not candidates:
        stats["macro_bail_reason"] = "no-candidates"
        return MacroPlan({}, [], stats)
    start = perf_counter()
    results: List[SoftResult] = []
    budget = cfg.budget_ms / 1000 if cfg.budget_ms > 0 else None
    macro_sims = 0
    for cell, digit in candidates:
        elapsed = perf_counter() - start
        if budget is not None and elapsed >= budget:
            stats["macro_bail_reason"] = "budget"
            break
        res = soft_simulate_guess(B, cell, digit, rules, cfg.soft_passes)
        macro_sims += 1
        results.append(res)
    stats["macro_build_time_ms"] = (perf_counter() - start) * 1000
    stats["macro_sims"] = macro_sims
    if not results:
        if stats["macro_bail_reason"] == "none":
            stats["macro_bail_reason"] = "empty"
        return MacroPlan({}, [], stats)

    def macro_key(res: SoftResult):
        return (
            STATUS_RANK.get(res.status, 3),
            -res.ns_gain,
            res.cand_after,
            res.passes,
            res.cell,
            res.digit,
        )

    results.sort(key=macro_key)
    per_cell_order: dict[int, List[int]] = {}
    if cfg.mode in {"order", "commit1", "commit2"}:
        for res in results:
            bucket = per_cell_order.setdefault(res.cell, [])
            if res.digit not in bucket:
                bucket.append(res.digit)
    return MacroPlan(per_cell_order, results, stats)


def apply_macro_commits(
    root: List[int],
    rules: Rules,
    cfg: MacroConfig,
    plan: MacroPlan,
) -> bool:
    stats = plan.stats
    stats["macro_commits"] = stats.get("macro_commits", 0)
    stats["macro_commit_type"] = stats.get("macro_commit_type", "none")
    if cfg.mode not in {"commit1", "commit2"}:
        return False
    commit_limits = 1 if cfg.mode == "commit1" else 2
    thresholds = [
        (8, 0.80),   # first commit threshold
        (12, 0.65),  # second commit threshold
    ]
    used: set[int] = set()
    commits = 0
    for step in range(commit_limits):
        gain_min, ratio = thresholds[min(step, len(thresholds) - 1)]
        candidate_idx = None
        candidate = None
        for idx, res in enumerate(plan.results):
            if idx in used:
                continue
            if not _should_commit(res, gain_min, ratio):
                continue
            if not has_candidate(root, res.cell, res.digit):
                used.add(idx)
                continue
            candidate_idx = idx
            candidate = res
            break
        if candidate is None:
            break
        trial = clone_state(root)
        if not place_structural(trial, candidate.cell, candidate.digit):
            used.add(candidate_idx)
            continue
        if not close_all(trial, rules):
            used.add(candidate_idx)
            continue
        for d in DIGITS:
            root[d] = trial[d]
        used.add(candidate_idx)
        commits += 1
    stats["macro_commits"] = commits
    stats["macro_commit_type"] = cfg.mode if commits else "none"
    return commits > 0


def try_guess(B: List[int], cell: int, digit: int, rules: Rules) -> List[int] | None:
    branch = clone_state(B)
    if not place_structural(branch, cell, digit):
        return None
    if not close_all(branch, rules):
        return None
    return branch


def dfs(
    B: List[int],
    rules: Rules,
    stats: dict,
    macro_plan: MacroPlan | None,
    depth: int = 0,
) -> List[int] | None:
    stats["nodes"] = stats.get("nodes", 0) + 1
    if is_solved(B):
        return B
    cell = choose_cell(B)
    if cell == -1:
        return None
    digits = order_digits(B, cell)
    if macro_plan and depth == 0:
        preferred = macro_plan.per_cell_order.get(cell, [])
        ordered = []
        seen = set()
        for d in preferred:
            if d in digits and d not in seen and has_candidate(B, cell, d):
                ordered.append(d)
                seen.add(d)
        for d in digits:
            if d not in seen:
                ordered.append(d)
        digits = ordered
    for digit in digits:
        result = try_guess(B, cell, digit, rules)
        if result is None:
            continue
        solved = dfs(result, rules, stats, macro_plan, depth + 1)
        if solved is not None:
            return solved
    return None


def eliminate_candidate(B: List[int], cell: int, digit: int, rules: Rules) -> bool:
    """Clear digit at cell and re-run closure. Return False on contradiction."""
    bit = BIT81[cell]
    if (B[digit] & bit) == 0:
        return True
    B[digit] &= ~bit
    return close_all(B, rules)


def board_to_string(B: List[int]) -> str:
    chars = []
    for c in CELLS:
        mask = cell_mask(B, c)
        if mask == 0:
            chars.append("0")
        elif _popcount(mask) == 1:
            digit = (mask & -mask).bit_length() - 1
            chars.append(str(digit + 1))
        else:
            chars.append(".")
    rows = ["".join(chars[r * 9:(r + 1) * 9]) for r in range(9)]
    return "\n".join(rows)


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


def build_S0(puzzle: str, rules: Rules) -> List[int]:
    B = [(1 << 81) - 1 for _ in DIGITS]
    for cell, ch in enumerate(puzzle):
        if ch in ".0":
            continue
        digit = int(ch) - 1
        if digit < 0 or digit > 8:
            raise ValueError(f"Invalid digit {ch}")
        if not place_structural(B, cell, digit):
            raise ValueError("Contradiction while applying clues")
    if not close_all(B, rules):
        raise ValueError("Contradiction after closure")
    debug_assert_state(B)
    return B


def solve_once(puzzle: str, rules: Rules, macro_cfg: MacroConfig) -> dict:
    s0_start = perf_counter()
    s0 = build_S0(puzzle, rules)
    s0_time = perf_counter() - s0_start
    macro_plan = build_macro_plan(s0, rules, macro_cfg)
    root_state = clone_state(s0)
    committed = apply_macro_commits(root_state, rules, macro_cfg, macro_plan)
    macro_stats = dict(macro_plan.stats)
    plan_for_dfs = macro_plan
    follow_stats = None
    if committed and macro_cfg.mode in {"commit1", "commit2"}:
        order_cfg = MacroConfig(
            mode="order",
            targets=macro_cfg.targets,
            soft_passes=macro_cfg.soft_passes,
            budget_ms=macro_cfg.budget_ms,
        )
        follow_plan = build_macro_plan(root_state, rules, order_cfg)
        follow_stats = dict(follow_plan.stats)
        macro_stats["macro_followup_sims"] = follow_stats.get("macro_sims", 0)
        macro_stats["macro_followup_time_ms"] = follow_stats.get("macro_build_time_ms", 0.0)
        macro_stats["macro_followup_bail"] = follow_stats.get("macro_bail_reason", "none")
        plan_for_dfs = follow_plan
    solve_start = perf_counter()
    stats: dict[str, int] = {}
    solution = dfs(root_state, rules, stats, plan_for_dfs)
    solve_time = perf_counter() - solve_start
    return {
        "success": solution is not None,
        "nodes": stats.get("nodes", 0),
        "s0_time_ms": s0_time * 1000.0,
        "solve_time_ms": solve_time * 1000.0,
        "macro_stats": macro_stats,
        "macro_follow_stats": follow_stats,
        "board": board_to_string(solution) if solution is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V9 solver with macro bridge")
    parser.add_argument("--puzzle", help="Single puzzle string (81 chars).")
    parser.add_argument("--puzzle-file", type=Path, help="Path to a text file with puzzles.")
    parser.add_argument(
        "--rules-profile",
        choices=["basic", "pairs", "full"],
        default="basic",
        help="Rule profile: basic(HS/NS), pairs(+NP), full(+NP+HP)",
    )
    parser.add_argument("--np", dest="np_override", action="store_const", const=True, help="Force enable naked pairs")
    parser.add_argument("--no-np", dest="np_override", action="store_const", const=False, help="Force disable naked pairs")
    parser.add_argument("--hp", dest="hp_override", action="store_const", const=True, help="Force enable hidden pairs")
    parser.add_argument("--no-hp", dest="hp_override", action="store_const", const=False, help="Force disable hidden pairs")
    parser.add_argument(
        "--macro-bridge",
        choices=["off", "order", "commit1", "commit2"],
        default="off",
    )
    parser.add_argument("--macro-targets", type=int, default=0)
    parser.add_argument("--macro-soft-passes", type=int, default=32)
    parser.add_argument("--macro-budget-ms", type=float, default=5.0)
    parser.add_argument("--start", type=int, default=0, help="0-based index of first puzzle to process.")
    parser.add_argument("--count", type=int, help="Maximum number of puzzles to process.")
    parser.add_argument("--runs", type=int, default=1, help="Number of attempts per puzzle.")
    parser.add_argument(
        "--timing-reps",
        type=int,
        default=1,
        help="Dataset repetitions (shuffles puzzles each rep).",
    )
    parser.add_argument("--shuffle-seed", type=int, default=1337, help="Seed used when timing reps > 1.")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-run logs.")
    parser.add_argument(
        "--locks-mode",
        choices=["off", "l1", "all"],
        default="all",
        help="Locks policy: disable, root-only, or all depths.",
    )
    parser.add_argument(
        "--hp-mode",
        choices=["off", "l1", "all"],
        default="off",
        help="Hidden-pair policy: disable, root-only, or all depths.",
    )
    parser.add_argument(
        "--macro-depth",
        type=int,
        default=0,
        help="Maximum DFS depth at which the macro bridge may run.",
    )
    parser.add_argument(
        "--results-db",
        type=Path,
        default=Path("solver_results.sqlite"),
        help="SQLite database path for recording run metadata.",
    )
    parser.set_defaults(np_override=None, hp_override=None)
    args = parser.parse_args()

    try:
        puzzles = _load_puzzles(args.puzzle, args.puzzle_file)
    except ValueError as exc:
        parser.error(str(exc))
        return
    if not puzzles:
        parser.error("No puzzles supplied.")
        return
    if args.start < 0:
        parser.error("--start must be non-negative.")
    if args.count is not None and args.count <= 0:
        parser.error("--count must be positive when provided.")
    if args.runs <= 0:
        parser.error("--runs must be positive.")
    if args.timing_reps <= 0:
        parser.error("--timing-reps must be positive.")

    script_name = Path(__file__).name
    dataset_label = (
        str(args.puzzle_file)
        if args.puzzle_file
        else ("inline_puzzle" if args.puzzle else "N/A")
    )
    use_np = False
    use_hp = False
    if args.rules_profile in {"pairs", "full"}:
        use_np = True
    if args.rules_profile == "full":
        use_hp = True
    if args.np_override is not None:
        use_np = args.np_override
    if args.hp_override is not None:
        use_hp = args.hp_override
    use_locks = args.locks_mode != "off"
    rules = Rules(
        use_np=use_np,
        use_hp=use_hp,
        use_locks=use_locks,
        hp_mode=args.hp_mode,
        locks_mode=args.locks_mode,
    )

    macro_cfg = MacroConfig(
        mode=args.macro_bridge,
        targets=args.macro_targets,
        soft_passes=args.macro_soft_passes,
        budget_ms=args.macro_budget_ms,
        max_depth=max(0, args.macro_depth),
    )

    selected = puzzles[args.start :]
    if args.count is not None:
        selected = selected[: args.count]
    if not selected:
        parser.error("Requested puzzle range produced no entries.")
    num_selected = len(selected)
    auto_show_board = (
        not args.quiet and num_selected == 1 and args.runs == 1 and args.timing_reps == 1
    )

    total_runs = 0
    solved_runs = 0
    sum_nodes = 0
    sum_s0_ms = 0.0
    sum_solve_ms = 0.0
    sum_solver_ms = 0.0
    per_run_totals: List[float] = []
    db_records: List[dict] = []
    overall_start = perf_counter()
    for rep in range(args.timing_reps):
        order = list(enumerate(selected, start=args.start))
        if args.timing_reps > 1:
            rnd = random.Random(args.shuffle_seed + rep)
            rnd.shuffle(order)
        for puzzle_index, puzzle in order:
            for run in range(args.runs):
                total_runs += 1
                result = solve_once(puzzle, rules, macro_cfg)
                if result["success"]:
                    solved_runs += 1
                sum_nodes += result["nodes"]
                sum_s0_ms += result["s0_time_ms"]
                sum_solve_ms += result["solve_time_ms"]
                per_run_total_ms = result["s0_time_ms"] + result["solve_time_ms"]
                sum_solver_ms += per_run_total_ms
                per_run_totals.append(per_run_total_ms)
                db_records.append(
                    {
                        "index": puzzle_index,
                        "status": "OK" if result["success"] else "FAIL",
                        "time_ms": per_run_total_ms,
                        "stats": {"nodes": result["nodes"]},
                        "puzzle": puzzle,
                        "solution": result["board"],
                        "verified": result["success"],
                        "error": None if result["success"] else "unsolved",
                        "rep_count": 1,
                        "solved_runs": 1 if result["success"] else 0,
                        "median_ms": per_run_total_ms,
                        "min_ms": per_run_total_ms,
                        "max_ms": per_run_total_ms,
                    }
                )
                if not args.quiet:
                    prefix = f"[p{puzzle_index} rep {rep + 1} run {run + 1}]"
                    status = "OK" if result["success"] else "FAIL"
                    macro_stats = result["macro_stats"]
                    macro_line = (
                        f"mode={macro_stats.get('macro_mode')} "
                        f"sims={macro_stats.get('macro_sims', 0)} "
                        f"time_ms={macro_stats.get('macro_build_time_ms', 0):.2f} "
                        f"bail={macro_stats.get('macro_bail_reason')} "
                        f"commits={macro_stats.get('macro_commits', 0)} "
                        f"commit_type={macro_stats.get('macro_commit_type')} "
                        f"pairs_ranked={macro_stats.get('macro_pairs_ranked', 0)} "
                        f"pairs_validated={macro_stats.get('macro_pairs_validated', 0)}"
                    )
                    print(
                        f"{prefix} {status} "
                        f"s0={result['s0_time_ms']:.2f} ms "
                        f"solve={result['solve_time_ms']:.2f} ms "
                        f"nodes={result['nodes']} "
                        f"total={per_run_total_ms:.2f} ms "
                        f"macro[{macro_line}]"
                    )
                    follow = result["macro_follow_stats"]
                    if follow:
                        print(
                            f"    follow-up sims={follow.get('macro_sims', 0)} "
                            f"time_ms={follow.get('macro_build_time_ms', 0):.2f} "
                            f"bail={follow.get('macro_bail_reason')}"
                        )
                    if (
                        auto_show_board
                        and result["success"]
                        and rep == 0
                        and run == 0
                        and result["board"]
                    ):
                        print(result["board"])

    total_elapsed = perf_counter() - overall_start
    if total_runs == 0:
        print("No runs executed.")
        return
    solved_pct = (solved_runs / total_runs) * 100.0
    avg_s0 = sum_s0_ms / total_runs
    avg_solve = sum_solve_ms / total_runs
    avg_nodes = sum_nodes / total_runs
    avg_solver = sum_solver_ms / total_runs
    median_solver = median(per_run_totals) if per_run_totals else 0.0
    min_solver = min(per_run_totals) if per_run_totals else 0.0
    max_solver = max(per_run_totals) if per_run_totals else 0.0
    p90_solver = _percentile(per_run_totals, 0.90)
    p95_solver = _percentile(per_run_totals, 0.95)
    print(f"Solved {solved_runs}/{total_runs} runs ({solved_pct:.1f}%).")
    print(
        "Solver stats (ms/run): "
        f"mean {avg_solver:.2f} | median {median_solver:.2f} | "
        f"p90 {p90_solver:.2f} | p95 {p95_solver:.2f} | "
        f"min {min_solver:.2f} | max {max_solver:.2f}"
    )
    print(
        f"Totals: solver {sum_solver_ms/1000.0:.2f} s | "
        f"avg s0={avg_s0:.2f} ms | avg solve={avg_solve:.2f} ms | "
        f"avg nodes={avg_nodes:.1f} | wall={(total_elapsed * 1000):.2f} ms"
    )

    if db_records:
        run_type = "timing" if args.timing_reps > 1 else "solve"
        command_line = shlex.join(sys.argv)
        with SolverDatabase(args.results_db) as db:
            recorded = db.record_run(
                script_name=script_name,
                command_line=command_line,
                dataset=dataset_label,
                args=args,
                run_records=db_records,
                html_report=None,
                run_type=run_type,
                timing_reps=args.timing_reps,
                total_time_ms=sum_solver_ms,
            )
        print(f"Run recorded in {args.results_db} (run_id={recorded.run_id}).")


if __name__ == "__main__":
    main()
