"""
Lightweight SQLite storage for solver runs and per-puzzle stats.
Keeps one row per run plus child rows for each processed puzzle.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _serialize_args(args: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for key, value in vars(args).items():
        if isinstance(value, Path):
            data[key] = str(value)
        else:
            data[key] = value
    return data


def _ensure_parent(path: Path) -> None:
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class RecordedRun:
    run_id: int


class SolverDatabase:
    """Simple SQLite wrapper for persisting solver run metadata."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        _ensure_parent(self.path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._init_schema()

    def __enter__(self) -> "SolverDatabase":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                script_name TEXT NOT NULL,
                command_line TEXT NOT NULL,
                dataset TEXT NOT NULL,
                puzzle_count INTEGER NOT NULL,
                solved_count INTEGER NOT NULL,
                avg_time_ms REAL,
                flags_json TEXT NOT NULL,
                html_report TEXT
            );

            CREATE TABLE IF NOT EXISTS puzzle_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                puzzle_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                time_ms REAL,
                nodes INTEGER,
                placements INTEGER,
                puzzle TEXT,
                solution TEXT,
                verified INTEGER,
                error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_puzzle_run_id ON puzzle_results(run_id);

            CREATE TABLE IF NOT EXISTS paper_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                dataset TEXT NOT NULL,
                reps INTEGER NOT NULL,
                sample_count INTEGER NOT NULL,
                solved INTEGER NOT NULL,
                total INTEGER NOT NULL,
                median_ms REAL,
                min_ms REAL,
                max_ms REAL,
                command_line TEXT NOT NULL,
                args_json TEXT NOT NULL,
                csv_path TEXT,
                meta_path TEXT
            );

            CREATE TABLE IF NOT EXISTS paper_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_run_id INTEGER NOT NULL REFERENCES paper_runs(id) ON DELETE CASCADE,
                rep INTEGER NOT NULL,
                puzzle_index INTEGER NOT NULL,
                puzzle TEXT,
                time_ns INTEGER,
                nodes INTEGER,
                placements INTEGER,
                solved INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_paper_samples_run_id ON paper_samples(paper_run_id);
            """
        )
        self.conn.commit()

        # Backfill columns for existing databases
        self._add_column("runs", "run_type", "TEXT DEFAULT 'solve'")
        self._add_column("runs", "timing_reps", "INTEGER DEFAULT 1")
        self._add_column("runs", "total_time_ms", "REAL")
        self._add_column("puzzle_results", "rep_count", "INTEGER DEFAULT 1")
        self._add_column("puzzle_results", "solved_runs", "INTEGER DEFAULT 1")
        self._add_column("puzzle_results", "median_ms", "REAL")
        self._add_column("puzzle_results", "min_ms", "REAL")
        self._add_column("puzzle_results", "max_ms", "REAL")

    def _add_column(self, table: str, column: str, definition: str) -> None:
        try:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition};")
        except sqlite3.OperationalError:
            # Column already exists
            pass

    def record_run(
        self,
        *,
        script_name: str,
        command_line: str,
        dataset: str,
        args: Any,
        run_records: List[Dict[str, Any]],
        html_report: Optional[Path],
        run_type: str,
        timing_reps: int,
        total_time_ms: float,
    ) -> RecordedRun:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        puzzle_count = len(run_records)
        solved_count = sum(1 for record in run_records if record.get("status") == "OK")
        total_time_ms = sum(
            float(record.get("time_ms") or 0.0) for record in run_records
        ) if total_time_ms is None else total_time_ms
        avg_time_ms = (total_time_ms / puzzle_count) if puzzle_count else None
        flags_json = json.dumps(_serialize_args(args))
        html_report_path = str(html_report) if html_report else None

        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO runs (
                    created_at, script_name, command_line, dataset,
                    puzzle_count, solved_count, avg_time_ms, total_time_ms,
                    flags_json, html_report, run_type, timing_reps
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    script_name,
                    command_line,
                    dataset,
                    puzzle_count,
                    solved_count,
                    avg_time_ms,
                    total_time_ms,
                    flags_json,
                    html_report_path,
                    run_type,
                    timing_reps,
                ),
            )
            run_id = int(cursor.lastrowid)
            puzzle_rows = [
                (
                    run_id,
                    record.get("index"),
                    record.get("status"),
                    record.get("time_ms"),
                    (record.get("stats") or {}).get("nodes"),
                    (record.get("stats") or {}).get("placements"),
                    record.get("puzzle"),
                    record.get("solution"),
                    1 if record.get("verified") else 0,
                    record.get("error"),
                    record.get("rep_count", 1),
                    record.get("solved_runs", 1),
                    record.get("median_ms"),
                    record.get("min_ms"),
                    record.get("max_ms"),
                )
                for record in run_records
            ]
            self.conn.executemany(
                """
                INSERT INTO puzzle_results (
                    run_id, puzzle_index, status, time_ms, nodes,
                    placements, puzzle, solution, verified, error,
                    rep_count, solved_runs, median_ms, min_ms, max_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                puzzle_rows,
            )
        return RecordedRun(run_id=run_id)

    def record_paper_run(
        self,
        *,
        dataset: str,
        reps: int,
        args: Any,
        command_line: str,
        csv_path: Path,
        meta_path: Path,
        summary: Dict[str, Any],
        samples: List[Dict[str, Any]],
    ) -> int:
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        args_payload = json.dumps(_serialize_args(args))
        solved = summary.get("solved", 0)
        total = summary.get("total", 0)
        sample_count = summary.get("samples", len(samples))
        with self.conn:
            cursor = self.conn.execute(
                """
                INSERT INTO paper_runs (
                    created_at, dataset, reps, sample_count,
                    solved, total, median_ms, min_ms, max_ms,
                    command_line, args_json, csv_path, meta_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    dataset,
                    reps,
                    sample_count,
                    solved,
                    total,
                    summary.get("median_ms"),
                    summary.get("min_ms"),
                    summary.get("max_ms"),
                    command_line,
                    args_payload,
                    str(csv_path),
                    str(meta_path),
                ),
            )
            paper_run_id = int(cursor.lastrowid)
            if samples:
                rows = [
                    (
                        paper_run_id,
                        sample.get("rep"),
                        sample.get("puzzle_index"),
                        sample.get("puzzle"),
                        sample.get("time_ns"),
                        sample.get("nodes"),
                        sample.get("placements"),
                        sample.get("solved"),
                    )
                    for sample in samples
                ]
                self.conn.executemany(
                    """
                    INSERT INTO paper_samples (
                        paper_run_id, rep, puzzle_index, puzzle,
                        time_ns, nodes, placements, solved
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
        return paper_run_id

    def update_html_report(self, run_id: int, html_report: Path) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET html_report = ? WHERE id = ?",
                (str(html_report), run_id),
            )
