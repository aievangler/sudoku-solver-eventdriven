"""V9 bitboard solver skeleton: phases 0-2 (S0 build + HS/NS + optional pairs)."""
from __future__ import annotations

import argparse
from pathlib import Path
from time import perf_counter
from dataclasses import dataclass
from typing import List

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
    mask |= sum(BIT81[p] for p in ROWS[ROW_OF[c]])
    mask |= sum(BIT81[p] for p in COLS[COL_OF[c]])
    mask |= sum(BIT81[p] for p in BOXES[BOX_OF[c]])
    mask &= ~BIT81[c]
    PEERS_MASK.append(mask)

STATUS_RANK = {"contradiction": 0, "solved": 1, "neutral": 2}


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


def _iter_bits(mask: int):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


@dataclass
class Rules:
    use_np: bool = False
    use_hp: bool = False


@dataclass
class MacroConfig:
    mode: str = "off"
    targets: int = 0
    soft_passes: int = 0
    budget_ms: float = 0.0


@dataclass
class SoftResult:
    cell: int
    digit: int
    status: str
    ns_gain: int
    cand_after: int
    passes: int


@dataclass
class MacroPlan:
    per_cell_order: dict[int, List[int]]
    results: List[SoftResult]
    stats: dict


def debug_assert_state(B: List[int]) -> None:
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
        return SoftResult(cell, digit, "contradiction", 0, base_cand, 0)
    ok, passes = _close_all(branch, rules, max_passes)
    if not ok:
        return SoftResult(cell, digit, "contradiction", 0, base_cand, passes)
    ns_gain = max(0, count_solved(branch) - base_solved)
    cand_after = total_candidates(branch)
    status = "solved" if is_solved(branch) else "neutral"
    return SoftResult(cell, digit, status, ns_gain, cand_after, passes)


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


def build_macro_plan(B: List[int], rules: Rules, cfg: MacroConfig) -> MacroPlan:
    stats: dict[str, object] = {
        "macro_mode": cfg.mode,
        "macro_sims": 0,
        "macro_bail_reason": "none",
        "macro_build_time_ms": 0.0,
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
    if cfg.mode == "order":
        for res in results:
            bucket = per_cell_order.setdefault(res.cell, [])
            if res.digit not in bucket:
                bucket.append(res.digit)
    return MacroPlan(per_cell_order, results, stats)


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


def load_puzzle(path: Path) -> str:
    """Return the first puzzle (81 chars) ignoring comments/blank lines."""
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        digits = [ch for ch in stripped if ch in "0123456789."]
        if len(digits) >= 81:
            return "".join(digits[:81])
    raise ValueError("Puzzle must contain at least 81 characters")


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


def main() -> None:
    parser = argparse.ArgumentParser(description="V9 S0 builder")
    parser.add_argument("--puzzle-file", type=Path, required=True)
    parser.add_argument("--use-np", action="store_true", help="Enable naked pairs in closure")
    parser.add_argument("--use-hp", action="store_true", help="Enable hidden pairs in closure")
    parser.add_argument("--macro-bridge", choices=["off", "order"], default="off")
    parser.add_argument("--macro-targets", type=int, default=0)
    parser.add_argument("--macro-soft-passes", type=int, default=32)
    parser.add_argument("--macro-budget-ms", type=float, default=5.0)
    args = parser.parse_args()
    puzzle = load_puzzle(args.puzzle_file)
    rules = Rules(use_np=args.use_np, use_hp=args.use_hp)
    macro_cfg = MacroConfig(
        mode=args.macro_bridge,
        targets=args.macro_targets,
        soft_passes=args.macro_soft_passes,
        budget_ms=args.macro_budget_ms,
    )
    s0_start = perf_counter()
    s0 = build_S0(puzzle, rules)
    s0_time = perf_counter() - s0_start
    print(f"Built S0 in {s0_time*1000:.2f} ms, hash={_state_hash(s0)}")
    macro_plan = build_macro_plan(s0, rules, macro_cfg)
    print(
        "Macro stats:",
        f"mode={macro_cfg.mode}",
        f"sims={macro_plan.stats.get('macro_sims', 0)}",
        f"time_ms={macro_plan.stats.get('macro_build_time_ms', 0):.2f}",
        f"bail={macro_plan.stats.get('macro_bail_reason')}",
    )
    solve_start = perf_counter()
    stats: dict[str, int] = {}
    solution = dfs(clone_state(s0), rules, stats, macro_plan)
    solve_time = perf_counter() - solve_start
    if solution is None:
        print(f"No solution found (nodes={stats.get('nodes', 0)}, solve_time={solve_time*1000:.2f} ms)")
    else:
        print(f"Solved in {solve_time*1000:.2f} ms, nodes={stats.get('nodes', 0)}")
        print(board_to_string(solution))


if __name__ == "__main__":
    main()
