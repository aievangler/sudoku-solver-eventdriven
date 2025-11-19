"""HTML report generation utilities for the Sudoku solver."""

from __future__ import annotations

import html
import json
import math
from argparse import Namespace
from datetime import datetime, timezone
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


def _display_dataset_label(value: Optional[str]) -> str:
    if not value:
        return "—"
    prefix = "testFileSets/"
    return value[len(prefix) :] if value.startswith(prefix) else value


def _format_timestamp_local(value: Any) -> str:
    if not isinstance(value, str):
        return str(value)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    localized = parsed.astimezone(local_tz)
    return localized.strftime("%Y-%m-%d %H:%M:%S %Z")


def _render_run_index(index_file: Path, runs: List[Dict[str, Any]]) -> None:
    dataset_values = sorted(
        {
            _display_dataset_label(str(entry.get("dataset", "")))
            for entry in runs
            if entry.get("dataset")
        }
    )
    command_values = sorted({entry.get("command", "") for entry in runs if entry.get("command")})
    dataset_options = "".join(
        f"<option value=\"{html.escape(value)}\"></option>"
        for value in dataset_values
        if value and value != "—"
    )
    command_options = "".join(
        f"<option value=\"{html.escape(value)}\"></option>" for value in command_values
    )

    hide_keys = {"results_db", "html_output", "export_csv", "export_meta", "quiet"}
    table_rows: List[str] = []
    for idx, entry in enumerate(runs, start=1):
        summary = entry.get("summary") or {}
        command_line = entry.get("command") or ""
        params = entry.get("args") or {}
        if isinstance(params, dict):
            param_pairs = [
                f"{html.escape(str(key))}={html.escape(str(value))}"
                for key, value in params.items()
                if key not in hide_keys
            ]
            params_html = "<br>".join(param_pairs) if param_pairs else "—"
        else:
            params_html = "—"
        detail = entry.get("detail_file")
        detail_html = (
            f"<a href=\"{html.escape(str(detail))}\" target=\"_blank\" rel=\"noopener noreferrer\">Open</a>"
            if detail
            else "—"
        )
        idx_link = str(idx)
        if detail:
            href = html.escape(str(detail))
            idx_link = f"<a href=\"{href}\" target=\"_blank\" rel=\"noopener noreferrer\">{idx}</a>"
        solved_display = f"{entry.get('solved', '—')}/{entry.get('total', '—')}"
        verified_display = f"{entry.get('verified', '—')}/{entry.get('total', '—')}"
        command_html = f"<code>{html.escape(command_line)}</code>" if command_line else "—"
        total_runtime = (entry.get("total_time_ms") or 0) / 1000.0
        fail_class = " class='fail-row'" if entry.get("solved") != entry.get("total") else ""
        dataset_raw = str(entry.get("dataset", ""))
        dataset_label = _display_dataset_label(dataset_raw)
        timestamp_display = _format_timestamp_local(entry.get("timestamp", "—"))
        table_rows.append(
            f"<tr{fail_class}>"
            f"<td><input type='checkbox' class='row-select' value='{idx}'></td>"
            f"<td class='sticky-col'>{idx_link}</td>"
            f"<td>{html.escape(timestamp_display)}</td>"
            f"<td>{html.escape(dataset_label)}</td>"
            f"<td>{html.escape(str(entry.get('script', '—')))}</td>"
            f"<td>{command_html}</td>"
            f"<td>{html.escape(str(entry.get('start', '—')))}</td>"
            f"<td>{html.escape(str(entry.get('count', '—')))}</td>"
            f"<td>{html.escape(solved_display)}</td>"
            f"<td>{html.escape(verified_display)}</td>"
            f"<td>{_format_ms(summary.get('p50') or summary.get('median'))}</td>"
            f"<td>{_format_ms(summary.get('p90'))}</td>"
            f"<td>{_format_ms(summary.get('p99'))}</td>"
            f"<td>{_format_ms(summary.get('mean'))}</td>"
            f"<td>{_format_ms(summary.get('max'))}</td>"
            f"<td>{total_runtime:.2f}</td>"
            f"<td>{params_html}</td>"
            f"<td>{detail_html}</td>"
            "</tr>"
        )

    table_body = "\n".join(table_rows)
    footer_cells = [
        "<th class='no-filter'></th>",
        "<th class='no-filter'></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th></th>",
        "<th class='no-filter'></th>",
    ]
    table_footer = "<tfoot><tr>" + "".join(footer_cells) + "</tr></tfoot>"

    datatables_css = "https://cdn.datatables.net/1.13.8/css/jquery.dataTables.min.css"
    datatables_buttons_css = "https://cdn.datatables.net/buttons/2.4.2/css/buttons.dataTables.min.css"
    searchbuilder_css = "https://cdn.datatables.net/searchbuilder/1.5.2/css/searchBuilder.dataTables.min.css"
    datetime_css = "https://cdn.datatables.net/datetime/1.5.0/css/dataTables.dateTime.min.css"
    jquery_js = "https://code.jquery.com/jquery-3.7.1.min.js"
    datatables_js = "https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js"
    datatables_buttons_js = "https://cdn.datatables.net/buttons/2.4.2/js/dataTables.buttons.min.js"
    datatables_colvis_js = "https://cdn.datatables.net/buttons/2.4.2/js/buttons.colVis.min.js"
    searchbuilder_js = "https://cdn.datatables.net/searchbuilder/1.5.2/js/dataTables.searchBuilder.min.js"
    datetime_js = "https://cdn.datatables.net/datetime/1.5.0/js/dataTables.dateTime.min.js"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>81-bit Solver Runs</title>
  <link rel="stylesheet" href="{datatables_css}">
  <link rel="stylesheet" href="{datatables_buttons_css}">
  <link rel="stylesheet" href="{searchbuilder_css}">
  <link rel="stylesheet" href="{datetime_css}">
  <style>
    :root {{
      color-scheme: dark;
      --bg: #070910;
      --panel: #121624;
      --panel-strong: #181d2f;
      --text: #e7e9fb;
      --border: #2e3350;
      --accent: #64c5ff;
      --muted: #95a2d3;
      --fail-bg: rgba(176, 40, 61, 0.35);
      --fail-border: #b0283d;
    }}
    * {{ box-sizing: border-box; }}
    body {{ font-family: "Segoe UI", Arial, sans-serif; background: var(--bg); color: var(--text); margin: 2rem; }}
    h1 {{ margin-bottom: 0.2rem; }}
    p.subtitle {{ margin-top: 0; color: var(--muted); }}
    .controls {{ display: flex; flex-direction: column; gap: 1rem; margin: 1rem 0 1.5rem; padding: 1rem; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; }}
    .filter-group {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
    label {{ font-size: 0.9rem; display: flex; flex-direction: column; gap: 0.2rem; color: var(--muted); }}
    input[type="text"] {{ background: var(--panel-strong); border: 1px solid var(--border); border-radius: 6px; padding: 0.4rem 0.6rem; color: var(--text); min-width: 220px; }}
    button.control {{ padding: 0.4rem 0.75rem; border-radius: 6px; border: 1px solid var(--border); background: var(--panel-strong); color: var(--text); cursor: pointer; }}
    button.control:hover {{ background: var(--accent); color: #02030a; }}
    .selection-tools {{ display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }}
    .selection-tools span {{ color: var(--muted); }}
    table.dataTable {{ width: 100% !important; background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }}
    table.dataTable thead th {{ background: var(--panel-strong); border-bottom: 0; color: var(--text); }}
    table.dataTable tbody tr.fail-row {{ background: var(--fail-bg); border-left: 3px solid var(--fail-border); }}
    table.dataTable tbody td {{ border-top: 1px solid var(--border); }}
    .sticky-col {{ position: sticky; left: 0; background: var(--panel-strong); z-index: 1; }}
    table.dataTable tbody td.sticky-col {{ background: var(--panel); }}
    code {{ color: var(--accent); font-size: 0.85rem; word-break: break-all; }}
    .dt-buttons .dt-button {{ background: var(--panel-strong) !important; border: 1px solid var(--border) !important; color: var(--text) !important; border-radius: 6px; }}
    .dt-buttons .dt-button:hover {{ background: var(--accent) !important; color: #010308 !important; }}
    table.dataTable tbody tr.dt-row-odd {{ background: rgba(255, 255, 255, 0.02); }}
    table.dataTable tbody tr.dt-row-even {{ background: rgba(255, 255, 255, 0.07); }}
    table.dataTable tfoot th {{ background: var(--panel-strong); color: var(--muted); padding: 0.35rem; }}
    table.dataTable tfoot input {{ width: 100%; padding: 0.3rem; border-radius: 4px; border: 1px solid var(--border); background: var(--panel); color: var(--text); font-size: 0.8rem; }}
    footer {{ margin-top: 2rem; color: var(--muted); font-size: 0.85rem; }}
  </style>
</head>
<body>
  <h1>81-bit Solver Run Index</h1>
  <p class="subtitle">Tracking {len(runs)} recent run(s).</p>
  <section class="controls">
    <div class="filter-group">
      <label>Dataset
        <input type="text" list="datasetOptions" id="datasetFilter" placeholder="Type or choose a dataset">
      </label>
      <label>Command
        <input type="text" list="commandOptions" id="commandFilter" placeholder="Type or choose a command">
      </label>
      <button class="control" id="clearFilters">Clear filters</button>
    </div>
    <div class="selection-tools">
      <button class="control" id="selectAll">Select page</button>
      <button class="control" id="clearSelection">Clear selection</button>
      <span>Selected runs: <strong id="selectedCount">0</strong></span>
    </div>
  </section>
  <table id="runsTable" class="display">
    <thead>
      <tr>
        <th>Select</th>
        <th>#</th>
        <th>Timestamp</th>
        <th>Dataset</th>
        <th>Script</th>
        <th>Command</th>
        <th>Start</th>
        <th>Count</th>
        <th>Solved</th>
        <th>Verified</th>
        <th>P50 (ms)</th>
        <th>P90 (ms)</th>
        <th>P99 (ms)</th>
        <th>Mean (ms)</th>
        <th>Max (ms)</th>
        <th>Total Runtime (s)</th>
        <th>Args</th>
        <th>Details</th>
      </tr>
    </thead>
    <tbody>
      {table_body}
    </tbody>
    {table_footer}
  </table>
  <datalist id="datasetOptions">{dataset_options}</datalist>
  <datalist id="commandOptions">{command_options}</datalist>
  <footer>
    DataTables with state saving keeps column visibility, sort order, and pagination between visits.
  </footer>
  <script src="{jquery_js}"></script>
  <script src="{datatables_js}"></script>
  <script src="{datatables_buttons_js}"></script>
  <script src="{datatables_colvis_js}"></script>
  <script src="{datetime_js}"></script>
  <script src="{searchbuilder_js}"></script>
  <script>
    document.addEventListener('DOMContentLoaded', function() {{
      const table = $('#runsTable').DataTable({{
        pageLength: 25,
        order: [[2, 'desc']],
        scrollX: true,
        stateSave: true,
        dom: 'Bfrtip',
        stripeClasses: ['dt-row-odd', 'dt-row-even'],
        columnDefs: [
          {{ targets: 0, orderable: false, searchable: false }},
          {{ targets: 5, visible: false }},
          {{ targets: 17, orderable: false, searchable: false }}
        ],
        buttons: [
          {{ extend: 'colvis', text: 'Columns' }},
          {{ extend: 'searchBuilder', text: 'Search Builder', config: {{ depthLimit: 2 }} }}
        ]
      }});

      $('#runsTable tfoot th').each(function(index) {{
        const cell = $(this);
        if (cell.hasClass('no-filter')) {{
          cell.empty();
          return;
        }}
        const title = $('#runsTable thead th').eq(index).text();
        cell.html('<input type="text" placeholder="Filter ' + title + '" />');
      }});

      table.columns().every(function(index) {{
        const footer = this.footer();
        if (!footer || footer.classList.contains('no-filter')) {{
          return;
        }}
        $('input', footer).on('input', function() {{
          table.column(index).search(this.value, false, true).draw();
        }});
      }});

      function applyFilter(inputId, columnIndex) {{
        const input = document.getElementById(inputId);
        input.addEventListener('input', function() {{
          table.column(columnIndex).search(this.value, false, true).draw();
        }});
      }}

      applyFilter('datasetFilter', 3);
      applyFilter('commandFilter', 5);

      document.getElementById('clearFilters').addEventListener('click', function() {{
        document.getElementById('datasetFilter').value = '';
        document.getElementById('commandFilter').value = '';
        table.column(3).search('').draw();
        table.column(5).search('').draw();
        table.columns().every(function(index) {{
          const footer = this.footer();
          if (!footer || footer.classList.contains('no-filter')) {{
            return;
          }}
          const input = footer.querySelector('input');
          if (input) {{
            input.value = '';
            table.column(index).search('').draw();
          }}
        }});
      }});

      function updateSelectedCount() {{
        const count = table.rows().nodes().to$().find('input.row-select:checked').length;
        document.getElementById('selectedCount').textContent = count.toString();
      }}

      $('#runsTable').on('change', 'input.row-select', updateSelectedCount);
      table.on('draw', updateSelectedCount);

      document.getElementById('selectAll').addEventListener('click', function() {{
        table.rows({{ page: 'current' }}).nodes().to$().find('input.row-select').prop('checked', true);
        updateSelectedCount();
      }});

      document.getElementById('clearSelection').addEventListener('click', function() {{
        table.rows().nodes().to$().find('input.row-select').prop('checked', false);
        updateSelectedCount();
      }});

      updateSelectedCount();
    }});
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
    datatables_css = "https://cdn.datatables.net/1.13.8/css/jquery.dataTables.min.css"
    datatables_buttons_css = "https://cdn.datatables.net/buttons/2.4.2/css/buttons.dataTables.min.css"
    jquery_js = "https://code.jquery.com/jquery-3.7.1.min.js"
    datatables_js = "https://cdn.datatables.net/1.13.8/js/jquery.dataTables.min.js"
    datatables_buttons_js = "https://cdn.datatables.net/buttons/2.4.2/js/dataTables.buttons.min.js"
    datatables_colvis_js = "https://cdn.datatables.net/buttons/2.4.2/js/buttons.colVis.min.js"

    detail_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>81-bit Solver Run Report</title>
  <link rel="stylesheet" href="{datatables_css}">
  <link rel="stylesheet" href="{datatables_buttons_css}">
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
    * {{ box-sizing: border-box; }}
    body {{ font-family: "Segoe UI", Arial, sans-serif; margin: 2rem; background: var(--bg); color: var(--text); }}
    h1, h2 {{ color: var(--text); }}
    table.dataTable {{ width: 100% !important; border: 1px solid var(--border); border-radius: 8px; background: var(--panel); color: var(--text); }}
    table.dataTable thead th {{ background-color: var(--panel-strong); border-bottom: 0; }}
    table.dataTable tbody td {{ border-top: 1px solid var(--border); }}
    .dt-buttons .dt-button {{ background: var(--panel-strong) !important; border: 1px solid var(--border) !important; color: var(--text) !important; border-radius: 6px; }}
    .dt-buttons .dt-button:hover {{ background: var(--accent) !important; color: #010308 !important; }}
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
    <table id="puzzleTable" class="display">
      {''.join(table_rows)}
    </table>
  </section>
  <script src="{jquery_js}"></script>
  <script src="{datatables_js}"></script>
  <script src="{datatables_buttons_js}"></script>
  <script src="{datatables_colvis_js}"></script>
  <script>
    document.addEventListener('DOMContentLoaded', function() {{
      $('#puzzleTable').DataTable({{
        pageLength: 25,
        order: [[0, 'asc']],
        dom: 'Bfrtip',
        buttons: [
          {{ extend: 'colvis', text: 'Columns' }}
        ],
        scrollX: true
      }});
    }});
  </script>
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
