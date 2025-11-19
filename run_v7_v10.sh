#!/usr/bin/env bash
# Batch runner for V7, V10 default, V10+L2, and V10 aggressive presets.

set -euo pipefail

DATASET="${1:-testFileSets/hard95_puzzles}"
RUNS="${RUNS:-1}"
REPS="${REPS:-1}"

echo "=== V7 baseline on ${DATASET} ==="
python3 planrun.py \
    --engine v7new \
    --puzzle-file "${DATASET}" \
    --runs "${RUNS}" \
    --timing-reps "${REPS}" \
    --quiet

echo "=== V10 default (single-wave 32, K=2) ==="
python3 planrun.py \
    --engine v10 \
    --puzzle-file "${DATASET}" \
    --single-wave-cap 32 \
    --k-cand 2 \
    --runs "${RUNS}" \
    --timing-reps "${REPS}" \
    --quiet

echo "=== V10 + L2 probe (node=2, puzzle=64) ==="
python3 planrun.py \
    --engine v10 \
    --puzzle-file "${DATASET}" \
    --single-wave-cap 32 \
    --k-cand 2 \
    --use-l2 \
    --l2-budget-node 2 \
    --l2-budget-puzzle 64 \
    --runs "${RUNS}" \
    --timing-reps "${REPS}" \
    --quiet

echo "=== V10 aggressive (wave=64, K=4, L2 heavy) ==="
python3 planrun.py \
    --engine v10 \
    --puzzle-file "${DATASET}" \
    --single-wave-cap 64 \
    --k-cand 4 \
    --use-l2 \
    --l2-budget-node 4 \
    --l2-budget-puzzle 128 \
    --runs "${RUNS}" \
    --timing-reps "${REPS}" \
    --quiet

echo "=== C++ solver (benchmark mode) ==="
python3 planrun.py \
    --engine cpp \
    --puzzle-file "${DATASET}" \
    --cpp-mode benchmark \
    --quiet

echo "All presets complete."
