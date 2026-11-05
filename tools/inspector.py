"""BoundRelay trace inspector: render a lesson's JSONL trace as a
self-contained offline HTML view (event lifecycle, state transitions,
payloads, optional result/attribution). Standard library only; no server,
no external assets; fails closed on invalid traces.

Usage:
  python tools/inspector.py --trace <path.jsonl> [--result <result.json>] [--out <path.html>]
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

REQUIRED_FIELDS = ("schema_version", "event_id", "run_id", "sequence",
                   "type", "timestamp", "source", "data")
KNOWN_SOURCES = ("typescript", "python", "go")
FAMILY = {
    "run.": "run", "step.": "step", "model.": "model", "tool.": "tool",
    "route.": "route", "handoff.": "handoff", "checkpoint.": "checkpoint",
    "approval.": "approval",
}


class TraceError(ValueError):
    """The trace file is not a valid BoundRelay JSONL trace."""


def reject_constant(name):
    raise TraceError(f"non-standard JSON constant: {name}")


def read_trace(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    events = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            raise TraceError(f"line {number}: blank records are not allowed")
        try:
            event = json.loads(line, parse_constant=reject_constant)
        except json.JSONDecodeError as error:
            raise TraceError(f"line {number}: invalid JSON ({error})") from error
        if not isinstance(event, dict):
            raise TraceError(f"line {number}: record must be an object")
        for field in REQUIRED_FIELDS:
            if field not in event:
                raise TraceError(f"line {number}: missing envelope field {field!r}")
        if event["schema_version"] != "1.0":
            raise TraceError(f"line {number}: unsupported envelope version")
        if event["source"] not in KNOWN_SOURCES:
            raise TraceError(f"line {number}: unknown source {event['source']!r}")
        if not isinstance(event["data"], dict):
            raise TraceError(f"line {number}: data must be an object")
        if not isinstance(event["sequence"], int) or event["sequence"] < 1:
            raise TraceError(f"line {number}: sequence must be a positive integer")
        if events and event["sequence"] != events[-1]["sequence"] + 1:
            raise TraceError(f"line {number}: sequence is not contiguous")
        if event["run_id"] != events[0]["run_id"] if events else False:
            raise TraceError(f"line {number}: run_id changed mid-trace")
        events.append(event)
    if not events:
        raise TraceError("trace contains no events")
    return events


def family_of(event_type: str) -> str:
    for prefix, family in FAMILY.items():
        if event_type.startswith(prefix):
            return family
    return "other"


def terminal_of(events: list[dict]) -> dict | None:
    terminals = [event for event in events if event["type"] in
                 ("run.completed", "run.failed", "run.cancelled")]
    return terminals[-1] if terminals else None


def render(events: list[dict], result: dict | None, trace_path: str) -> str:
    run_id = html.escape(events[0]["run_id"])
    source = html.escape(events[0]["source"])
    rows = []
    for event in events:
        family = family_of(event["type"])
        data = json.dumps(event["data"], sort_keys=True, ensure_ascii=True)
        step = html.escape(str(event["data"].get("step_name")
                               or event["data"].get("step") or ""))
        rows.append(
            f'<tr class="ev {family}"><td>{event["sequence"]}</td>'
            f'<td><span class="tag {family}">{html.escape(event["type"])}</span></td>'
            f'<td>{step}</td><td><details><summary>data</summary>'
            f'<pre>{html.escape(data)}</pre></details></td></tr>')
    result_section = ""
    if result is not None:
        attribution = json.dumps(result.get("attribution", {}),
                                 sort_keys=True, ensure_ascii=True, indent=1)
        keys = ("status", "failure_code", "synthesis_invoked",
                "approval_decision", "effect_status", "reconciled")
        summary = "".join(
            f'<div class="kv"><span class="k">{html.escape(key)}</span>'
            f'<span class="v">{html.escape(json.dumps(result.get(key)))}</span></div>'
            for key in keys if key in result)
        result_section = (
            f'<section id="result"><h2>Result</h2>{summary}'
            f'<h3>Attribution</h3><pre>{html.escape(attribution)}</pre></section>')
    counts: dict[str, int] = {}
    for event in events:
        counts[family_of(event["type"])] = counts.get(family_of(event["type"]), 0) + 1
    badges = "".join(f'<span class="tag {family}">{family}: {count}</span>'
                     for family, count in sorted(counts.items()))
    return TEMPLATE.format(run_id=run_id, source=source, count=len(events),
                           trace=html.escape(trace_path), badges=badges,
                           timeline="".join(rows), result_section=result_section)


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>BoundRelay trace {run_id}</title>
<style>
body{{font-family:ui-monospace,Consolas,monospace;margin:2rem;color:#1a1a2e;background:#fafafa}}
h1{{font-size:1.2rem}} h2{{font-size:1rem;margin-top:1.5rem}}
.badges{{margin:.5rem 0}} .tag{{display:inline-block;padding:.1rem .45rem;margin:.1rem;
border-radius:.6rem;font-size:.75rem;background:#e8e8f0}}
.tag.run{{background:#dbeafe}}.tag.step{{background:#dcfce7}}.tag.model{{background:#fae8ff}}
.tag.tool{{background:#fef3c7}}.tag.route{{background:#e0e7ff}}.tag.handoff{{background:#ccfbf1}}
.tag.checkpoint{{background:#fee2e2}}.tag.approval{{background:#f3e8ff}}.tag.other{{background:#eeeeee}}
table{{border-collapse:collapse;width:100%;background:#fff}}
td,th{{border:1px solid #e2e2ea;padding:.3rem .5rem;text-align:left;font-size:.8rem}}
tr.ev.failed td{{background:#fff1f2}} tr.ev.checkpoint td{{background:#fffbeb}}
details summary{{cursor:pointer;color:#4b4b6e}} pre{{white-space:pre-wrap;font-size:.72rem;margin:.2rem}}
.kv{{display:flex;gap:.6rem}} .kv .k{{min-width:11rem;color:#55556e}} .kv .v{{font-weight:bold}}
</style></head><body>
<h1>BoundRelay trace</h1>
<p>run <b>{run_id}</b> · source <b>{source}</b> · {count} events · <code>{trace}</code></p>
<div class="badges">{badges}</div>
{result_section}
<section id="timeline"><h2>Event timeline</h2>
<table><tr><th>#</th><th>type</th><th>step</th><th>data</th></tr>
{timeline}
</table></section>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a BoundRelay JSONL trace as offline HTML")
    parser.add_argument("--trace", required=True, help="path to the JSONL trace")
    parser.add_argument("--result", help="optional path to the run result JSON")
    parser.add_argument("--out", help="output HTML path (default: <trace>.html)")
    args = parser.parse_args(argv)
    trace_path = Path(args.trace)
    try:
        events = read_trace(trace_path)
    except (TraceError, OSError) as error:
        print(f"inspector: {error}", file=sys.stderr)
        return 2
    result = None
    if args.result:
        try:
            result = json.loads(Path(args.result).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            print(f"inspector: result file invalid: {error}", file=sys.stderr)
            return 2
        if not isinstance(result, dict):
            print("inspector: result must be a JSON object", file=sys.stderr)
            return 2
    page = render(events, result, str(trace_path))
    out = Path(args.out) if args.out else trace_path.with_suffix(".html")
    out.write_text(page, encoding="utf-8")
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
