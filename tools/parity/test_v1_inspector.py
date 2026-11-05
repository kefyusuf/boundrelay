"""P2 trace-inspector probes: fail-closed parsing, self-contained rendering,
payload escaping, result/attribution rendering, CLI exit codes."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from tools import inspector  # noqa: E402


def event(sequence, event_type, source="python", step=None, data=None):
    payload = {"schema_version": "1.0", "event_id": f"evt-{sequence}",
               "run_id": "run-1", "sequence": sequence, "type": event_type,
               "timestamp": "2026-11-06T00:00:00Z", "source": source,
               "data": data if data is not None else {}}
    if step is not None:
        payload["data"] = {"step_name": step, **payload["data"]}
    return payload


def write_trace(path, events):
    path.write_text("".join(json.dumps(event) + "\n" for event in events),
                    encoding="utf-8")


SAMPLE = [event(1, "run.created", data={"scenario_id": "order-brief"}),
          event(2, "run.started", data={"scenario_id": "order-brief"}),
          event(3, "step.started", step="worker.order-details"),
          event(4, "step.completed", step="worker.order-details",
                data={"outcome": {"worker_id": "order-details", "status": "SUCCEEDED"}}),
          event(5, "run.completed", data={"status": "SUCCEEDED"})]


class InspectorParseTests(unittest.TestCase):
    def test_valid_trace_parses_and_is_contiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.jsonl"
            write_trace(path, SAMPLE)
            events = inspector.read_trace(path)
            self.assertEqual(len(events), 5)
            self.assertEqual(events[-1]["type"], "run.completed")

    def test_blank_line_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.jsonl"
            path.write_text(json.dumps(SAMPLE[0]) + "\n\n", encoding="utf-8")
            with self.assertRaises(inspector.TraceError):
                inspector.read_trace(path)

    def test_nan_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.jsonl"
            path.write_text(json.dumps(SAMPLE[0])[:-1] + ', "x": NaN}\n', encoding="utf-8")
            with self.assertRaises(inspector.TraceError):
                inspector.read_trace(path)

    def test_missing_envelope_field_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.jsonl"
            broken = {key: value for key, value in SAMPLE[0].items() if key != "source"}
            path.write_text(json.dumps(broken) + "\n", encoding="utf-8")
            with self.assertRaises(inspector.TraceError):
                inspector.read_trace(path)

    def test_sequence_gap_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.jsonl"
            write_trace(path, [SAMPLE[0], SAMPLE[2]])
            with self.assertRaises(inspector.TraceError):
                inspector.read_trace(path)

    def test_unknown_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.jsonl"
            write_trace(path, [event(1, "run.created", source="ruby")])
            with self.assertRaises(inspector.TraceError):
                inspector.read_trace(path)

    def test_empty_trace_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.jsonl"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(inspector.TraceError):
                inspector.read_trace(path)


class InspectorRenderTests(unittest.TestCase):
    def test_render_is_self_contained_and_escapes_payloads(self):
        hostile = event(1, "step.started", step="<script>alert(1)</script>",
                        data={"payload": "<img src=x onerror=alert(1)>"})
        page = inspector.render([hostile, SAMPLE[0]], None, "t.jsonl")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)
        self.assertIn("Event timeline", page)

    def test_render_includes_result_and_attribution(self):
        result = {"status": "SUCCEEDED", "failure_code": None,
                  "attribution": {"steps": [], "totals": {"latency_ms": 0}}}
        page = inspector.render(SAMPLE, result, "t.jsonl")
        self.assertIn("Attribution", page)
        self.assertIn("SUCCEEDED", page)

    def test_failure_rows_marked(self):
        events = SAMPLE[:4] + [event(5, "run.failed", data={"status": "FAILED",
                                                            "failure_code": "ALL_WORKERS_FAILED"})]
        page = inspector.render(events, None, "t.jsonl")
        self.assertIn("run.failed", page)
        self.assertIn("ALL_WORKERS_FAILED", page)


class InspectorCliTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools/inspector.py"), *args],
                              capture_output=True, text=True, cwd=ROOT)

    def test_cli_writes_html_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "t.jsonl"
            out = Path(directory) / "t.html"
            write_trace(trace, SAMPLE)
            completed = self.run_cli("--trace", str(trace), "--out", str(out))
            self.assertEqual(completed.returncode, 0, completed.stderr)
            page = out.read_text(encoding="utf-8")
            self.assertIn("Event timeline", page)
            self.assertEqual(completed.stdout.strip(), str(out))

    def test_cli_rejects_invalid_trace_with_exit_two(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "t.jsonl"
            trace.write_text("not json\n", encoding="utf-8")
            completed = self.run_cli("--trace", str(trace))
            self.assertEqual(completed.returncode, 2)
            self.assertIn("inspector:", completed.stderr)

    def test_cli_rejects_invalid_result_with_exit_two(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "t.jsonl"
            write_trace(trace, SAMPLE)
            result = Path(directory) / "r.json"
            result.write_text("[1,2]\n", encoding="utf-8")
            completed = self.run_cli("--trace", str(trace), "--result", str(result))
            self.assertEqual(completed.returncode, 2)

    def test_real_lesson_trace_renders(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "m3.jsonl"
            result = Path(directory) / "r.json"
            args = ["--mode", "parallel", "--case", "parallel-complete",
                    "--trace", str(trace)]
            import os
            env = {**os.environ, "PYTHONPATH": str(ROOT / "lessons/03-parallel-fanout-fanin/python/src")}
            completed = subprocess.run([sys.executable, "-m", "boundrelay_m3", *args],
                                       capture_output=True, text=True, cwd=ROOT, env=env, check=True)
            result.write_text(completed.stdout.strip(), encoding="utf-8")
            html_path = Path(directory) / "m3.html"
            rendered = self.run_cli("--trace", str(trace), "--result", str(result),
                                    "--out", str(html_path))
            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            page = html_path.read_text(encoding="utf-8")
            self.assertIn("worker.order-details", page)
            self.assertIn("Attribution", page)
            self.assertIn("SUCCEEDED", page)


if __name__ == "__main__":
    unittest.main()
