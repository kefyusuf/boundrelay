from pathlib import Path
import tempfile
import unittest

from tools.parity.normalize import normalize_event, normalize_result, normalized_trace, read_jsonl


class NormalizeTests(unittest.TestCase):
    def test_event_removes_only_volatile_fields(self) -> None:
        event = {
            "schema_version": "1.0",
            "event_id": "evt-ts",
            "run_id": "run-ts",
            "sequence": 1,
            "timestamp": "2026-09-02T00:00:00Z",
            "source": "typescript",
            "type": "route.selected",
            "data": {"route": "billing"},
        }
        self.assertEqual(
            normalize_event(event),
            {
                "schema_version": "1.0",
                "sequence": 1,
                "type": "route.selected",
                "data": {"route": "billing"},
            },
        )

    def test_result_removes_run_and_path_but_keeps_behavior(self) -> None:
        result = {
            "schema_version": "1.0",
            "run_id": "run-ts",
            "scenario_id": "support-triage",
            "case_id": "x",
            "mode": "model",
            "status": "FAILED",
            "selected_route": None,
            "specialist_invoked": False,
            "failure_code": "INVALID_ROUTE_DECISION",
            "trace_path": "volatile",
        }
        normalized = normalize_result(result)
        self.assertNotIn("run_id", normalized)
        self.assertNotIn("trace_path", normalized)
        self.assertEqual(normalized["failure_code"], "INVALID_ROUTE_DECISION")

    def test_jsonl_reader_rejects_empty_or_non_object_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                read_jsonl(path)
            path.write_text("[]\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "object"):
                normalized_trace(path)

    def test_jsonl_reader_rejects_nonstandard_numeric_constants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            for constant in ("NaN", "Infinity", "-Infinity"):
                with self.subTest(constant=constant):
                    path.write_text(
                        '{"type":"model.completed","data":{"confidence":' + constant + '}}\n',
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(ValueError, "non-standard JSON constant"):
                        read_jsonl(path)

    def test_jsonl_reader_rejects_blank_physical_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace.jsonl"
            path.write_text(
                '{"type":"run.created","data":{}}\n\n'
                '{"type":"run.completed","data":{}}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "blank.*line 2"):
                read_jsonl(path)


if __name__ == "__main__":
    unittest.main()
