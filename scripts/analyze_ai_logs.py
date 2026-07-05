"""Analyze LLM interaction logs produced by the sqlseed-ai plugin.

Reads JSON log files from the ai_logs cache directory and emits a structured
report covering overview statistics, per-table and per-stage breakdowns,
repeat-call (self-correction) detection, token-waste analysis, failure-pattern
detection, and a time-distribution histogram.

The script streams files one at a time and only retains aggregated statistics
plus small top-N metadata entries in memory, so it can handle large log
directories without loading every file's full content simultaneously.

Usage:
    python scripts/analyze_ai_logs.py
    python scripts/analyze_ai_logs.py --log-dir /path/to/logs
    python scripts/analyze_ai_logs.py --output report.txt
    python scripts/analyze_ai_logs.py --json
    python -m scripts.analyze_ai_logs
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlseed._utils.logger import get_logger
from sqlseed._utils.paths import get_cache_dir

logger = get_logger(__name__)

# Regex to extract the column name from the user message content. Matches a
# line like "  name: employee_id" (typical of column-analysis prompts emitted
# by the sqlseed-ai plugin). The column identifier must start with a letter or
# underscore followed by word characters.
_COLUMN_NAME_RE = re.compile(r"^\s*name:\s*([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)

# Time histogram buckets: (label, lower_inclusive, upper_exclusive_or_None).
# The last bucket uses upper=None to mean "no upper bound".
_HISTOGRAM_BUCKETS: list[tuple[str, float, float | None]] = [
    ("<1s", 0.0, 1.0),
    ("1-5s", 1.0, 5.0),
    ("5-10s", 5.0, 10.0),
    ("10-30s", 10.0, 30.0),
    ("30-60s", 30.0, 60.0),
    (">60s", 60.0, None),
]

_TOP_TABLES = 20
_TOP_REPEATS = 30
_TOP_PROMPTS = 10
_TOP_EXAMPLES = 5
_PREVIEW_CHARS = 100
_EMPTY_STAGE_LABEL = "(unstaged)"
_EMPTY_TABLE_LABEL = "(empty)"


# ---------------------------------------------------------------------------
# Type-coercion helpers (JSON values are Any; narrow to concrete types safely)
# ---------------------------------------------------------------------------


def _coerce_float(value: Any, default: float = 0.0) -> float:
    """Coerce a JSON-decoded value to float, returning *default* on failure.

    Booleans are rejected because ``isinstance(True, int)`` is True in Python
    but a boolean is not a meaningful elapsed-seconds value.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


def _coerce_str(value: Any, default: str = "") -> str:
    """Coerce a JSON-decoded value to str, returning *default* on failure."""
    if isinstance(value, str):
        return value
    return default


def _extract_message_content(messages: Any, role: str, *, last: bool = False) -> str:
    """Return the content of the first (or last) message with the given role.

    Args:
        messages: The ``messages`` list from a log entry (type is ``Any``
            because it comes from JSON).
        role: The role to match (e.g. ``"user"``, ``"system"``).
        last: If True, scan from the end and return the last matching message;
            otherwise return the first match.
    """
    if not isinstance(messages, list):
        return ""
    iterable: list[Any] = list(reversed(messages)) if last else messages
    for msg in iterable:
        if isinstance(msg, dict) and msg.get("role") == role:
            return _coerce_str(msg.get("content"))
    return ""


def _extract_column_name(user_content: str) -> str:
    """Extract the column name from the user message content.

    Looks for a line matching ``name: <column>`` (typical of column-analysis
    prompts emitted by the sqlseed-ai plugin). Returns an empty string if no
    match is found.
    """
    match = _COLUMN_NAME_RE.search(user_content)
    return match.group(1) if match else ""


def _parse_json_response(response: str) -> dict[str, Any] | None:
    """Parse the LLM response as JSON, stripping markdown code fences.

    Returns the parsed dict on success, or None if the response is empty, not
    valid JSON, or not a JSON object.
    """
    if not response:
        return None
    cleaned = response.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute the p-th percentile (0-100) of a pre-sorted list.

    Uses linear interpolation between the two closest ranks, matching the
    default behavior of ``numpy.percentile`` with ``interpolation='linear'``.
    """
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (p / 100.0) * (len(sorted_values) - 1)
    lower = int(k)
    upper = min(lower + 1, len(sorted_values) - 1)
    if lower == upper:
        return sorted_values[lower]
    weight = k - lower
    return sorted_values[lower] + weight * (sorted_values[upper] - sorted_values[lower])


# ---------------------------------------------------------------------------
# Accumulator dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GroupStats:
    """Aggregated statistics for a group (table, stage, or table+column)."""

    count: int = 0
    total_time: float = 0.0
    max_time: float = 0.0

    def add(self, elapsed: float) -> None:
        """Record a single observation."""
        self.count += 1
        self.total_time += elapsed
        if elapsed > self.max_time:
            self.max_time = elapsed

    @property
    def avg_time(self) -> float:
        """Average elapsed time per call."""
        return self.total_time / self.count if self.count else 0.0


@dataclass
class PromptInfo:
    """Metadata for a prompt/response entry, used in top-N rankings."""

    file_name: str
    char_count: int
    preview: str
    table: str
    column: str


@dataclass
class FailurePattern:
    """Accumulator for a failure pattern: count + example file names."""

    count: int = 0
    examples: list[str] = field(default_factory=list)

    def record(self, file_name: str) -> None:
        """Record an occurrence, keeping at most _TOP_EXAMPLES example names."""
        self.count += 1
        if len(self.examples) < _TOP_EXAMPLES:
            self.examples.append(file_name)


@dataclass
class AnalysisState:
    """Mutable accumulator for the streaming analysis pass."""

    total_files: int = 0
    skipped: int = 0
    elapsed_values: list[float] = field(default_factory=list)
    timestamps: list[str] = field(default_factory=list)
    models: set[str] = field(default_factory=set)
    table_stats: dict[str, GroupStats] = field(default_factory=dict)
    stage_stats: dict[str, GroupStats] = field(default_factory=dict)
    repeat_stats: dict[tuple[str, str], GroupStats] = field(default_factory=dict)
    repeat_files: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    total_input_chars: int = 0
    total_output_chars: int = 0
    system_prompts: list[PromptInfo] = field(default_factory=list)
    user_prompts: list[PromptInfo] = field(default_factory=list)
    responses: list[PromptInfo] = field(default_factory=list)
    null_generator: FailurePattern = field(default_factory=FailurePattern)
    derive_from: FailurePattern = field(default_factory=FailurePattern)
    malformed_json: FailurePattern = field(default_factory=FailurePattern)
    column_mismatch: FailurePattern = field(default_factory=FailurePattern)


def _add_to_group(stats: dict[str, GroupStats], key: str, elapsed: float) -> None:
    """Helper to record an observation under a string key."""
    group = stats.get(key)
    if group is None:
        group = GroupStats()
        stats[key] = group
    group.add(elapsed)


def _add_to_repeat(
    stats: dict[tuple[str, str], GroupStats],
    files: dict[tuple[str, str], list[str]],
    key: tuple[str, str],
    elapsed: float,
    file_name: str,
) -> None:
    """Helper to record an observation under a (table, column) key."""
    group = stats.get(key)
    if group is None:
        group = GroupStats()
        stats[key] = group
    group.add(elapsed)
    file_list = files.get(key)
    if file_list is None:
        file_list = []
        files[key] = file_list
    file_list.append(file_name)


# ---------------------------------------------------------------------------
# Per-file analysis
# ---------------------------------------------------------------------------


def analyze_file(path: Path, state: AnalysisState) -> None:
    """Process a single log file and update *state* in place.

    Skips malformed files with a warning (logged to stderr via structlog) and
    increments ``state.skipped`` without raising.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("skip_unreadable_file", path=str(path), error=str(e))
        state.skipped += 1
        return
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("skip_invalid_json", path=str(path), error=str(e))
        state.skipped += 1
        return
    if not isinstance(data, dict):
        logger.warning("skip_not_object", path=str(path))
        state.skipped += 1
        return

    state.total_files += 1

    timestamp = _coerce_str(data.get("timestamp"))
    model = _coerce_str(data.get("model"))
    stage = _coerce_str(data.get("stage"))
    table_name = _coerce_str(data.get("table_name"))
    elapsed = _coerce_float(data.get("elapsed_seconds"))
    messages = data.get("messages")
    response = _coerce_str(data.get("response"))

    system_content = _extract_message_content(messages, "system", last=False)
    user_content = _extract_message_content(messages, "user", last=True)
    column_name = _extract_column_name(user_content)

    # --- Overview ---
    state.elapsed_values.append(elapsed)
    if timestamp:
        state.timestamps.append(timestamp)
    if model:
        state.models.add(model)

    # --- Per-table (skip empty table_name) ---
    if table_name:
        _add_to_group(state.table_stats, table_name, elapsed)

    # --- Per-stage (empty -> "(unstaged)") ---
    stage_key = stage if stage else _EMPTY_STAGE_LABEL
    _add_to_group(state.stage_stats, stage_key, elapsed)

    # --- Repeat call detection (table_name, column_name) ---
    if column_name:
        key = (table_name, column_name)
        _add_to_repeat(state.repeat_stats, state.repeat_files, key, elapsed, path.name)

    # --- Token waste ---
    input_chars = len(system_content) + len(user_content)
    output_chars = len(response)
    state.total_input_chars += input_chars
    state.total_output_chars += output_chars

    state.system_prompts.append(
        PromptInfo(
            file_name=path.name,
            char_count=len(system_content),
            preview=system_content[:_PREVIEW_CHARS],
            table=table_name,
            column=column_name,
        )
    )
    state.user_prompts.append(
        PromptInfo(
            file_name=path.name,
            char_count=len(user_content),
            preview=user_content[:_PREVIEW_CHARS],
            table=table_name,
            column=column_name,
        )
    )
    state.responses.append(
        PromptInfo(
            file_name=path.name,
            char_count=output_chars,
            preview=response[:_PREVIEW_CHARS],
            table=table_name,
            column=column_name,
        )
    )

    # --- Failure patterns ---
    parsed = _parse_json_response(response)
    if parsed is None:
        state.malformed_json.record(path.name)
        return

    # null generator: explicitly set to null (cross-column derivation signal).
    if "generator" in parsed and parsed["generator"] is None:
        state.null_generator.record(path.name)

    # derive_from: non-null, non-empty value (cross-column derivation).
    derive_value = parsed.get("derive_from")
    if derive_value:
        state.derive_from.record(path.name)

    # column mismatch: response column differs from the requested column.
    resp_column = _coerce_str(parsed.get("column"))
    if column_name and resp_column and resp_column != column_name:
        state.column_mismatch.record(path.name)


def analyze_logs(log_dir: Path) -> AnalysisState:
    """Stream all *.json log files in *log_dir* and return aggregated state."""
    state = AnalysisState()
    if not log_dir.exists():
        logger.warning("log_dir_not_found", log_dir=str(log_dir))
        return state
    files = sorted(log_dir.glob("*.json"))
    if not files:
        logger.warning("no_log_files_found", log_dir=str(log_dir))
        return state
    for path in files:
        analyze_file(path, state)
    return state


# ---------------------------------------------------------------------------
# Report construction
# ---------------------------------------------------------------------------


def _breakdown_rows(
    stats: dict[str, GroupStats],
    *,
    top_n: int | None = None,
    skip_empty: bool = False,
) -> list[dict[str, Any]]:
    """Convert a GroupStats dict into a sorted list of row dicts."""
    rows: list[dict[str, Any]] = []
    for name, group in stats.items():
        if skip_empty and not name:
            continue
        rows.append(
            {
                "name": name,
                "count": group.count,
                "total_time": round(group.total_time, 3),
                "avg_time": round(group.avg_time, 3),
                "max_time": round(group.max_time, 3),
            }
        )
    rows.sort(key=lambda r: (r["total_time"], r["count"]), reverse=True)
    if top_n is not None:
        rows = rows[:top_n]
    return rows


def _repeat_rows(
    stats: dict[tuple[str, str], GroupStats],
    files: dict[tuple[str, str], list[str]],
    *,
    top_n: int,
) -> list[dict[str, Any]]:
    """Convert repeat-call GroupStats into sorted row dicts (count > 1 only)."""
    rows: list[dict[str, Any]] = []
    for (table, column), group in stats.items():
        if group.count <= 1:
            continue
        rows.append(
            {
                "table": table or _EMPTY_TABLE_LABEL,
                "column": column,
                "count": group.count,
                "total_time": round(group.total_time, 3),
                "example_files": files.get((table, column), [])[:_TOP_EXAMPLES],
            }
        )
    rows.sort(key=lambda r: (r["count"], r["total_time"]), reverse=True)
    return rows[:top_n]


def _top_prompts(items: list[PromptInfo], *, top_n: int) -> list[dict[str, Any]]:
    """Return the top-N PromptInfo entries by char_count, descending."""
    sorted_items = sorted(items, key=lambda p: p.char_count, reverse=True)
    return [
        {
            "file_name": p.file_name,
            "char_count": p.char_count,
            "preview": p.preview,
            "table": p.table,
            "column": p.column,
        }
        for p in sorted_items[:top_n]
    ]


def _histogram_rows(elapsed: list[float]) -> list[dict[str, Any]]:
    """Bucket elapsed_seconds into predefined ranges."""
    rows: list[dict[str, Any]] = []
    for label, lower, upper in _HISTOGRAM_BUCKETS:
        if upper is None:
            count = sum(1 for v in elapsed if v >= lower)
        else:
            count = sum(1 for v in elapsed if lower <= v < upper)
        rows.append({"label": label, "count": count})
    return rows


def _failure_dict(pattern: FailurePattern) -> dict[str, Any]:
    """Serialize a FailurePattern into a plain dict."""
    return {"count": pattern.count, "examples": list(pattern.examples)}


def build_report(state: AnalysisState) -> dict[str, Any]:
    """Build the report data structure from accumulated *state*."""
    elapsed = sorted(state.elapsed_values)
    total_time = sum(elapsed)
    avg = statistics.mean(elapsed) if elapsed else 0.0

    report: dict[str, Any] = {
        "overview": {
            "total_files": state.total_files,
            "skipped_files": state.skipped,
            "total_llm_time": round(total_time, 3),
            "avg_elapsed": round(avg, 3),
            "min_elapsed": round(min(elapsed), 3) if elapsed else 0.0,
            "max_elapsed": round(max(elapsed), 3) if elapsed else 0.0,
            "p50_elapsed": round(_percentile(elapsed, 50), 3),
            "p95_elapsed": round(_percentile(elapsed, 95), 3),
            "p99_elapsed": round(_percentile(elapsed, 99), 3),
            "time_span": {
                "oldest": min(state.timestamps) if state.timestamps else "",
                "newest": max(state.timestamps) if state.timestamps else "",
            },
            "distinct_models": sorted(state.models),
        },
        "per_table": {
            "top_n": _TOP_TABLES,
            "rows": _breakdown_rows(state.table_stats, top_n=_TOP_TABLES, skip_empty=True),
        },
        "per_stage": {
            "top_n": None,
            "rows": _breakdown_rows(state.stage_stats, top_n=None),
        },
        "repeat_calls": {
            "top_n": _TOP_REPEATS,
            "rows": _repeat_rows(state.repeat_stats, state.repeat_files, top_n=_TOP_REPEATS),
        },
        "token_waste": {
            "total_input_chars": state.total_input_chars,
            "total_output_chars": state.total_output_chars,
            "input_output_ratio": (
                round(state.total_input_chars / state.total_output_chars, 3)
                if state.total_output_chars > 0
                else 0.0
            ),
            "top_system_prompts": _top_prompts(state.system_prompts, top_n=_TOP_PROMPTS),
            "top_user_prompts": _top_prompts(state.user_prompts, top_n=_TOP_PROMPTS),
            "top_responses": _top_prompts(state.responses, top_n=_TOP_PROMPTS),
        },
        "failure_patterns": {
            "null_generator": _failure_dict(state.null_generator),
            "derive_from": _failure_dict(state.derive_from),
            "malformed_json": _failure_dict(state.malformed_json),
            "column_mismatch": _failure_dict(state.column_mismatch),
        },
        "time_histogram": _histogram_rows(elapsed),
    }
    return report


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------


def _fmt_time(value: float) -> str:
    """Format a seconds value with 2 decimal places and an 's' suffix."""
    return f"{value:.2f}s"


def _render_breakdown_table(title: str, rows: list[dict[str, Any]], name_header: str) -> list[str]:
    """Render a breakdown table (name + count/total/avg/max) as text lines."""
    lines: list[str] = [title, "-" * 80]
    if not rows:
        lines.append("  (no entries)")
        lines.append("")
        return lines
    lines.append(
        f"  {name_header:<30} {'CALLS':>8} {'TOTAL_TIME':>12} "
        f"{'AVG_TIME':>12} {'MAX_TIME':>12}"
    )
    for r in rows:
        lines.append(
            f"  {r['name']:<30} {r['count']:>8} {_fmt_time(r['total_time']):>12} "
            f"{_fmt_time(r['avg_time']):>12} {_fmt_time(r['max_time']):>12}"
        )
    lines.append("")
    return lines


def render_text(report: dict[str, Any]) -> str:
    """Render the report as a human-readable plain-text string."""
    lines: list[str] = []
    sep = "=" * 80
    lines.append(sep)
    lines.append("AI LOGS ANALYSIS REPORT".center(80))
    lines.append(sep)
    lines.append("")

    # 1. Overview
    ov = report["overview"]
    lines.append("1. OVERVIEW")
    lines.append("-" * 80)
    lines.append(f"  Total log files:        {ov['total_files']}")
    lines.append(f"  Skipped (malformed):    {ov['skipped_files']}")
    lines.append(f"  Total LLM time:         {_fmt_time(ov['total_llm_time'])}")
    lines.append(f"  Average per call:       {_fmt_time(ov['avg_elapsed'])}")
    lines.append(f"  Min elapsed:            {_fmt_time(ov['min_elapsed'])}")
    lines.append(f"  Max elapsed:            {_fmt_time(ov['max_elapsed'])}")
    lines.append(f"  P50:                    {_fmt_time(ov['p50_elapsed'])}")
    lines.append(f"  P95:                    {_fmt_time(ov['p95_elapsed'])}")
    lines.append(f"  P99:                    {_fmt_time(ov['p99_elapsed'])}")
    span = ov["time_span"]
    lines.append(f"  Time span (oldest):     {span['oldest']}")
    lines.append(f"  Time span (newest):     {span['newest']}")
    models = ov["distinct_models"]
    lines.append(f"  Distinct models:        {', '.join(models) if models else '(none)'}")
    lines.append("")

    # 2. Per-Table
    pt = report["per_table"]
    lines.extend(
        _render_breakdown_table(
            f"2. PER-TABLE BREAKDOWN (top {pt['top_n']} by total time, empty skipped)",
            pt["rows"],
            "TABLE",
        )
    )

    # 3. Per-Stage
    ps = report["per_stage"]
    lines.extend(_render_breakdown_table("3. PER-STAGE BREAKDOWN", ps["rows"], "STAGE"))

    # 4. Repeat Calls
    rc = report["repeat_calls"]
    lines.append(f"4. REPEAT CALL DETECTION (top {rc['top_n']} by count, self-correction loops)")
    lines.append("-" * 80)
    rc_rows = rc["rows"]
    if not rc_rows:
        lines.append("  (no repeated column calls detected)")
    else:
        lines.append(f"  {'TABLE':<25} {'COLUMN':<25} {'COUNT':>6} {'TOTAL_TIME':>12}")
        for r in rc_rows:
            lines.append(
                f"  {r['table']:<25} {r['column']:<25} {r['count']:>6} "
                f"{_fmt_time(r['total_time']):>12}"
            )
    lines.append("")

    # 5. Token Waste
    tw = report["token_waste"]
    lines.append("5. TOKEN WASTE ANALYSIS")
    lines.append("-" * 80)
    lines.append(f"  Total input chars:   {tw['total_input_chars']}")
    lines.append(f"  Total output chars:  {tw['total_output_chars']}")
    lines.append(f"  Input/output ratio:  {tw['input_output_ratio']:.2f}")
    lines.append("")
    for label, key in [
        ("largest system prompts", "top_system_prompts"),
        ("largest user prompts", "top_user_prompts"),
        ("largest responses", "top_responses"),
    ]:
        items = tw[key]
        lines.append(f"  Top {len(items)} {label}:")
        if not items:
            lines.append("    (none)")
        for i, p in enumerate(items, 1):
            table_lbl = p["table"] or "(none)"
            col_lbl = p["column"] or "(none)"
            lines.append(
                f"    {i}. [{p['char_count']} chars] table={table_lbl}, column={col_lbl}"
            )
            lines.append(f"       file: {p['file_name']}")
            lines.append(f"       preview: {p['preview']!r}")
        lines.append("")

    # 6. Failure Patterns
    fp = report["failure_patterns"]
    lines.append("6. FAILURE PATTERN DETECTION")
    lines.append("-" * 80)
    lines.append(f"  Null generator responses:    {fp['null_generator']['count']}")
    lines.append(f"  Derive_from responses:       {fp['derive_from']['count']}")
    lines.append(f"  Malformed JSON responses:    {fp['malformed_json']['count']}")
    lines.append(f"  Column name mismatches:      {fp['column_mismatch']['count']}")
    lines.append("")
    for name, label in [
        ("null_generator", "Null generator"),
        ("derive_from", "Derive_from"),
        ("malformed_json", "Malformed JSON"),
        ("column_mismatch", "Column mismatch"),
    ]:
        pat = fp[name]
        if pat["examples"]:
            lines.append(f"  Examples ({label}):")
            for ex in pat["examples"]:
                lines.append(f"    - {ex}")
            lines.append("")

    # 7. Time Distribution Histogram
    hist = report["time_histogram"]
    lines.append("7. TIME DISTRIBUTION HISTOGRAM")
    lines.append("-" * 80)
    max_count = max((b["count"] for b in hist), default=0)
    for bucket in hist:
        bar_width = (bucket["count"] * 40 // max_count) if max_count > 0 else 0
        bar = "#" * bar_width
        lines.append(f"  {bucket['label']:<10} {bucket['count']:>6}  {bar}")
    lines.append("")
    lines.append(sep)

    return "\n".join(lines)


def render_json(report: dict[str, Any]) -> str:
    """Render the report as a JSON string with 2-space indentation."""
    return json.dumps(report, indent=2, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        description="Analyze LLM interaction logs produced by the sqlseed-ai plugin.",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Directory containing JSON log files. "
        "Defaults to get_cache_dir('ai_logs').",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write report to this file instead of stdout.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    log_dir: Path = args.log_dir if args.log_dir is not None else get_cache_dir("ai_logs")

    if not log_dir.exists():
        print(f"ERROR: log directory does not exist: {log_dir}", file=sys.stderr)
        return 1

    state = analyze_logs(log_dir)
    report = build_report(state)

    output_text = render_json(report) if args.json else render_text(report)

    if args.output is not None:
        try:
            args.output.write_text(output_text + "\n", encoding="utf-8")
        except OSError as e:
            print(f"ERROR: failed to write output file: {e}", file=sys.stderr)
            return 1
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
