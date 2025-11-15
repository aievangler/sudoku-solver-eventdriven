"""HTML report generation utilities for the Sudoku solver."""

from __future__ import annotations

import html
import json
import math
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Sequence

try:
    from datetime import UTC
except ImportError:  # pragma: no cover
    from datetime import timezone as _timezone

    UTC = _timezone.utc  # type: ignore[assignment]


def _serialize_param_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, tuple):
        return [_serialize_param_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_param_value(item) for item in value]
    return value


def _slugify_label(text: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in text)
    cleaned = "_".join(filter(None, cleaned.split("_")))
    return cleaned or "run"


def _next_detail_path(repo_dir: Path, dataset_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    base_name = dataset_path.stem or dataset_path.name or "dataset"
    slug = _slugify_label(base_name)
    base = f"{timestamp}_{slug}" if slug else timestamp
    candidate = repo_dir / f"{base}.html"
    counter = 1
    while candidate.exists():
        candidate = repo_dir / f"{base}_{counter}.html"
        counter += 1
    return candidate


def _load_runs_manifest(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    runs = data.get("runs")
    if not isinstance(runs, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for entry in runs:
        if isinstance(entry, dict):
            normalized.append(entry)
    return normalized


def _save_runs_manifest(path: Path, runs: List[Dict[str, Any]]) -> None:
    payload = {"runs": runs}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_detail_json(detail_path: Path, payload: Dict[str, Any]) -> Path:
    json_path = detail_path.with_suffix(".json")
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return json_path


def _format_ms(value: Any) -> str:
    return f"{value:.2f}" if isinstance(value, (int, float)) else "n/a"


def _percentile(sorted_values: Sequence[float], pct: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * (pct / 100.0)
    lower_idx = math.floor(position)
    upper_idx = math.ceil(position)
    if lower_idx == upper_idx:
        return float(sorted_values[int(position)])
    lower = sorted_values[lower_idx]
    upper = sorted_values[upper_idx]
    return float(lower + (upper - lower) * (position - lower_idx))


def _render_run_index(index_file: Path, runs: List[Dict[str, Any]]) -> None:
    header_row = (
        "<tr>"
        "<th class='sticky-col'>#</th>"
        "<th>Timestamp</th>"
        "<th>Python File</th>"
        "<th>Dataset</th>"
        "<th>Start</th>"
        "<th>Count</th>"
        "<th>Solved</th>"
        "<th>Verified</th>"
        "<th>P50 (ms)</th>"
        "<th>P80 (ms)</th>"
        "<th>P90 (ms)</th>"
        "<th>P95 (ms)</th>"
        "<th>P99 (ms)</th>"
        "<th>Mean (ms)</th>"
        "<th>Max (ms)</th>"
        "<th>Total Runtime (s)</th>"
        "<th>Command</th>"
        "<th>Input Params</th>"
        "<th>Details</th>"
        "</tr>"
    )
    rows: List[str] = []
    for idx, entry in enumerate(runs, start=1):
        summary = entry.get("summary") or {}
        command = entry.get("command") or ""
        command_html = f"<code>{html.escape(command)}</code>" if command else "—"
        params = entry.get("args") or {}
        if isinstance(params, dict):
            param_pairs = [
                f"{html.escape(str(key))}={html.escape(str(value))}"
                for key, value in params.items()
            ]
            params_html = "<br>".join(param_pairs) if param_pairs else "—"
        else:
            params_html = "—"
        detail = entry.get("detail_file")
        detail_html = (
            f"<a href=\"{html.escape(str(detail))}\">Open</a>"
            if detail
            else "—"
        )
        idx_link = str(idx)
        if detail:
            href = html.escape(str(detail))
            idx_link = f"<a href=\"{href}\" target=\"_blank\" rel=\"noopener noreferrer\">{idx}</a>"
        solved_display = f"{entry.get('solved', '—')}/{entry.get('total', '—')}"
        verified_display = f"{entry.get('verified', '—')}/{entry.get('total', '—')}"
        highlight_fail = entry.get("solved") != entry.get("total")
        row_class = " class='fail-row'" if highlight_fail else ""
        rows.append(
            f"<tr{row_class} data-dataset=\"{html.escape(str(entry.get('dataset', '')))}\" "
            f"data-script=\"{html.escape(str(entry.get('script', '')))}\" "
            f"data-command=\"{html.escape(command)}\">"
            f"<td class='sticky-col'>{idx_link}</td>"
            f"<td>{html.escape(str(entry.get('timestamp', '—')))}</td>"
            f"<td>{html.escape(str(entry.get('script', '—')))}</td>"
            f"<td>{html.escape(str(entry.get('dataset', '—')))}</td>"
            f"<td>{html.escape(str(entry.get('start', '—')))}</td>"
            f"<td>{html.escape(str(entry.get('count', '—')))}</td>"
            f"<td>{html.escape(solved_display)}</td>"
            f"<td>{html.escape(verified_display)}</td>"
            f"<td>{_format_ms(summary.get('p50') or summary.get('median'))}</td>"
            f"<td>{_format_ms(summary.get('p80'))}</td>"
            f"<td>{_format_ms(summary.get('p90'))}</td>"
            f"<td>{_format_ms(summary.get('p95'))}</td>"
            f"<td>{_format_ms(summary.get('p99'))}</td>"
            f"<td>{_format_ms(summary.get('mean'))}</td>"
            f"<td>{_format_ms(summary.get('max'))}</td>"
            f"<td>{(entry.get('total_time_ms') or 0) / 1000:.2f}</td>"
            f"<td>{command_html}</td>"
            f"<td>{params_html}</td>"
            f"<td>{detail_html}</td>"
            "</tr>"
        )

    css = """
    :root {
      color-scheme: dark;
      --bg: #0b0d13;
      --panel: #141824;
      --panel-strong: #1d2233;
      --text: #e8ecff;
      --border: #2c3144;
      --muted: #98a1c6;
      --accent: #5bc0ff;
      --fail-bg: #3a1111;
      --fail-text: #ff9f9f;
    }
    * { box-sizing: border-box; }
    body { font-family: "Segoe UI", Arial, sans-serif; margin: 2rem; background: var(--bg); color: var(--text); }
    table { border-collapse: collapse; width: 100%; border-radius: 10px; overflow: auto; border: 1px solid var(--border); background: var(--panel); }
    th, td { border: 1px solid var(--border); padding: 0.55rem 0.7rem; text-align: left; vertical-align: top; }
    th { background-color: var(--panel-strong); }
    code { font-family: 'Courier New', monospace; font-size: 0.85rem; white-space: pre-wrap; word-break: break-word; color: var(--accent); }
    td:nth-child(16), td:nth-child(17) { max-width: 320px; }
    .fail-row { background: var(--fail-bg); color: var(--fail-text); }
    a { color: var(--accent); }
    .filter-row { display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }
    .filter-row input { padding: 0.4rem 0.6rem; background: var(--panel); border: 1px solid var(--border); color: var(--text); border-radius: 4px; }
    .sticky-col { position: sticky; left: 0; background: var(--panel-strong); z-index: 2; }
    td.sticky-col { background: var(--panel); }
    """

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>81-bit Solver Run Index</title>
  <style>{css}</style>
</head>
<body>
  <h1>81-bit Solver Run Index</h1>
  <p>Recording {len(runs)} run(s) with command lines and parameters.</p>
  <div class="filter-row">
    <label>Dataset filter<br><input id="datasetFilter" onkeyup="filterTable()" placeholder="e.g. hard95"></label>
    <label>Script filter<br><input id="scriptFilter" onkeyup="filterTable()" placeholder="python file"></label>
    <label>Command filter<br><input id="commandFilter" onkeyup="filterTable()" placeholder="args substring"></label>
  </div>
  <table>
    <thead>{header_row}</thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <script>
    function filterTable() {{
      const datasetVal = document.getElementById("datasetFilter").value.toLowerCase();
      const scriptVal = document.getElementById("scriptFilter").value.toLowerCase();
      const commandVal = document.getElementById("commandFilter").value.toLowerCase();
      const rows = document.querySelectorAll("tbody tr");
      rows.forEach(row => {{
        const dataset = row.getAttribute("data-dataset") || "";
        const script = row.getAttribute("data-script") || "";
        const command = row.getAttribute("data-command") || "";
        const match = dataset.toLowerCase().includes(datasetVal) &&
                      script.toLowerCase().includes(scriptVal) &&
                      command.toLowerCase().includes(commandVal);
        row.style.display = match ? "" : "none";
      }});
    }}
  </script>
</body>
</html>
"""
    index_file.write_text(html_content, encoding="utf-8")


def generate_html_report(
    output_path: Path,
    args: Namespace,
    run_records: List[Dict[str, Any]],
    script_name: str,
    command_line: str,
    format_us_func,
    db_run_id: Optional[int] = None,
    total_time_ms: Optional[float] = None,
) -> Path:
    output_path = Path(output_path)
    is_directory = output_path.suffix.lower() != ".html"
    dataset_label = str(args.puzzle_file) if args.puzzle_file else ("inline_puzzle" if args.puzzle else "N/A")
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    if is_directory:
        repo_dir = output_path
        repo_dir.mkdir(parents=True, exist_ok=True)
        dataset_path = args.puzzle_file if args.puzzle_file else Path("inline_puzzle")
        detail_path = _next_detail_path(repo_dir, dataset_path)
    else:
        detail_path = output_path
        detail_path.parent.mkdir(parents=True, exist_ok=True)

    solved = sum(1 for record in run_records if record["status"] == "OK")
    verified_total = sum(1 for record in run_records if record.get("verified"))
    total = len(run_records)
    times = [
        record["time_ms"]
        for record in run_records
        if isinstance(record.get("time_ms"), (int, float))
    ]
    summary: Dict[str, Any] = {
        "total": total,
        "solved": solved,
        "percent_solved": (solved / total * 100.0) if total else 0.0,
        "verified": verified_total,
    }
    if total_time_ms is not None:
        summary["total_runtime_ms"] = total_time_ms
        summary["total_runtime_s"] = total_time_ms / 1000.0
    if times:
        sorted_times = sorted(times)
        summary.update(
            {
                "min": sorted_times[0],
                "median": median(sorted_times),
                "mean": mean(sorted_times),
                "max": sorted_times[-1],
                "p50": _percentile(sorted_times, 50.0),
                "p80": _percentile(sorted_times, 80.0),
                "p90": _percentile(sorted_times, 90.0),
                "p95": _percentile(sorted_times, 95.0),
                "p99": _percentile(sorted_times, 99.0),
            }
        )

    params_payload = {
        key: _serialize_param_value(getattr(args, key)) for key in sorted(vars(args))
    }

    format_us = format_us_func
    has_core_breakdown = any(
        isinstance(record.get("stats"), dict)
        and any(key in record["stats"] for key in ("prop_ms", "score_ms", "dfs_ms"))
        for record in run_records
    )
    header_cols = [
        "<th>#</th>",
        "<th>Status</th>",
        "<th>Mean (ms)</th>",
        "<th>Median (ms)</th>",
        "<th>Min (ms)</th>",
        "<th>Max (ms)</th>",
        "<th>Nodes</th>",
        "<th>Placements</th>",
        "<th>Runs</th>",
    ]
    if has_core_breakdown:
        header_cols.extend(
            [
                "<th>Prop (ms)</th>",
                "<th>Score (ms)</th>",
                "<th>DFS (ms)</th>",
            ]
        )
    header_cols.extend(
        [
            "<th>Error</th>",
            "<th>Input Puzzle</th>",
            "<th>Solution</th>",
        ]
    )
    table_rows = ["<tr>" + "".join(header_cols) + "</tr>"]
    for record in run_records:
        stats = record.get("stats") or {}
        failed = record.get("status") != "OK"
        row_class = " class='fail-row'" if failed else ""
        row_cells = [
            f"<td>{record['index']}</td>",
            f"<td>{html.escape(record['status'])}</td>",
            f"<td>{_format_ms(record.get('time_ms'))}</td>",
            f"<td>{_format_ms(record.get('median_ms'))}</td>",
            f"<td>{_format_ms(record.get('min_ms'))}</td>",
            f"<td>{_format_ms(record.get('max_ms'))}</td>",
            f"<td>{stats.get('nodes', '—')}</td>",
            f"<td>{stats.get('placements', '—')}</td>",
            f"<td>{record.get('solved_runs', '—')}/{record.get('rep_count', '—')}</td>",
        ]
        if has_core_breakdown:
            row_cells.extend(
                [
                    f"<td>{_format_ms(stats.get('prop_ms'))}</td>",
                    f"<td>{_format_ms(stats.get('score_ms'))}</td>",
                    f"<td>{_format_ms(stats.get('dfs_ms'))}</td>",
                ]
            )
        row_cells.extend(
            [
                f"<td>{html.escape(record.get('error') or '—')}</td>",
                f"<td><code>{html.escape(record['puzzle'])}</code></td>",
                f"<td><code>{html.escape(record.get('solution') or '—')}</code></td>",
            ]
        )
        table_rows.append(f"<tr{row_class}>" + "".join(row_cells) + "</tr>")

    run_failed = solved != total
    db_list_item = f"<li><strong>Database Run ID:</strong> {db_run_id}</li>" if db_run_id else ""
    summary_class = "summary-card fail-card" if run_failed else "summary-card ok-card"
    detail_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>81-bit Solver Run Report</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0f1117;
      --panel: #1b1f2a;
      --panel-strong: #23283b;
      --text: #e5e5e5;
      --muted: #a0a6c0;
      --border: #2f3447;
      --accent: #4db5ff;
      --fail-bg: #3b1212;
      --fail-text: #ffb3b3;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{ font-family: "Segoe UI", Arial, sans-serif; margin: 2rem; background: var(--bg); color: var(--text); }}
    h1, h2 {{ color: var(--text); }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; background: var(--panel); border-radius: 8px; overflow: hidden; }}
    th, td {{ border: 1px solid var(--border); padding: 0.55rem 0.7rem; text-align: left; }}
    th {{ background-color: var(--panel-strong); }}
    code {{ font-family: 'Courier New', monospace; font-size: 0.9rem; color: var(--accent); }}
    ul {{ list-style: disc; margin-left: 1.5rem; color: var(--muted); }}
    .summary-card {{ background: var(--panel); border: 1px solid var(--border); padding: 1rem 1.25rem; border-radius: 10px; margin-bottom: 1.5rem; }}
    .fail-card {{ border-color: #a32626; background: #2c0f0f; color: var(--fail-text); }}
    .ok-card {{ border-color: #1f6feb; }}
    .fail-row {{ background-color: var(--fail-bg); color: var(--fail-text); }}
    a {{ color: var(--accent); }}
    .fail-note {{ color: var(--fail-text); font-weight: 600; }}
  </style>
</head>
<body>
  <h1>81-bit Solver Run Report</h1>
  <section class="{summary_class}">
    <h2>Summary</h2>
    <ul>
      <li><strong>Total Puzzles:</strong> {total}</li>
      <li><strong>Solved:</strong> {solved}</li>
      <li><strong>Script:</strong> {html.escape(script_name)}</li>
      {db_list_item}
      <li><strong>Percent Solved:</strong> {summary.get("percent_solved", 0.0):.1f}%</li>
      { "<li class='fail-note'>⚠ Not all puzzles solved</li>" if run_failed else "" }
      <li><strong>Verified:</strong> {summary.get("verified", 0)}</li>
      <li><strong>Min:</strong> {_format_ms(summary.get("min"))} ({format_us(summary.get("min"))})</li>
      <li><strong>Median (P50):</strong> {_format_ms(summary.get("p50") or summary.get("median"))} ({format_us(summary.get("p50") or summary.get("median"))})</li>
      <li><strong>P80:</strong> {_format_ms(summary.get("p80"))} ({format_us(summary.get("p80"))})</li>
      <li><strong>P90:</strong> {_format_ms(summary.get("p90"))} ({format_us(summary.get("p90"))})</li>
      <li><strong>P95:</strong> {_format_ms(summary.get("p95"))} ({format_us(summary.get("p95"))})</li>
      <li><strong>P99:</strong> {_format_ms(summary.get("p99"))} ({format_us(summary.get("p99"))})</li>
      <li><strong>Max:</strong> {_format_ms(summary.get("max"))} ({format_us(summary.get("max"))})</li>
      {f"<li><strong>Total Runtime:</strong> {summary.get('total_runtime_s', 0.0):.2f} s</li>" if summary.get("total_runtime_s") is not None else ""}
    </ul>
  </section>
  <section>
    <h2>CLI Parameters</h2>
    <ul>
      {''.join(f"<li><strong>{html.escape(str(k))}:</strong> {html.escape(str(v))}</li>" for k, v in params_payload.items())}
    </ul>
  </section>
  <section>
    <h2>Puzzle Details</h2>
    <table>
      {''.join(table_rows)}
    </table>
  </section>
</body>
</html>
"""
    detail_path.write_text(detail_html, encoding="utf-8")
    report_payload = {
        "script": script_name,
        "command": command_line,
        "dataset": dataset_label,
        "detail_file": detail_path.name,
        "summary": summary,
        "args": params_payload,
        "run_records": run_records,
        "generated_at": timestamp,
        "db_run_id": db_run_id,
        "total_time_ms": total_time_ms,
    }
    _write_detail_json(detail_path, report_payload)

    if not is_directory:
        return detail_path

    manifest_path = output_path / "runs_manifest.json"
    existing_runs = _load_runs_manifest(manifest_path)
    entry = {
        "timestamp": timestamp,
        "script": script_name,
        "command": command_line,
        "dataset": dataset_label,
        "detail_file": detail_path.name,
        "summary": summary,
        "bucket_summaries": {},
        "args": params_payload,
        "solved": solved,
        "verified": verified_total,
        "total": total,
        "count": total,
        "start": args.start,
        "runs": args.runs,
        "db_run_id": db_run_id,
        "total_time_ms": total_time_ms,
    }
    runs = [entry] + existing_runs
    runs = runs[:200]
    _save_runs_manifest(manifest_path, runs)
    _render_run_index(output_path / "index.html", runs)
    return detail_path
