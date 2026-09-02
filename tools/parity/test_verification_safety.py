from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_m0 import clear_previous_evidence, main
from tools.parity.verify_m0 import (
    EVENT_SCHEMA_PATH,
    _assert_trace,
    _validator,
    assert_clean_worktree,
)


class VerificationSafetyTests(unittest.TestCase):
    @patch("tools.parity.verify_m0.subprocess.check_output")
    def test_clean_worktree_is_accepted(self, check_output) -> None:
        check_output.return_value = ""

        assert_clean_worktree()

        check_output.assert_called_once_with(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
        )

    @patch("tools.parity.verify_m0.subprocess.check_output")
    def test_dirty_worktree_is_rejected_before_certification(self, check_output) -> None:
        check_output.return_value = " M tools/parity/verify_m0.py\n?? new-file.txt\n"

        with self.assertRaisesRegex(RuntimeError, "clean Git worktree"):
            assert_clean_worktree()

    def test_previous_evidence_is_removed_before_a_new_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / ".boundrelay/m0"
            output_root.mkdir(parents=True)
            evidence = output_root / "verification-evidence.json"
            evidence.write_text('{"status":"PASSED"}\n', encoding="utf-8")

            clear_previous_evidence(output_root)

            self.assertFalse(output_root.exists())


    def test_trace_events_must_match_the_result_run_id(self) -> None:
        events = [
            {
                "schema_version": "1.0",
                "event_id": "evt-1",
                "run_id": "run-result",
                "sequence": 1,
                "type": "run.created",
                "timestamp": "2026-09-02T00:00:00Z",
                "source": "python",
                "data": {},
            },
            {
                "schema_version": "1.0",
                "event_id": "evt-2",
                "run_id": "run-other",
                "sequence": 2,
                "type": "run.completed",
                "timestamp": "2026-09-02T00:00:01Z",
                "source": "python",
                "data": {},
            },
        ]

        with self.assertRaisesRegex(AssertionError, "wrong run_id"):
            _assert_trace(
                events,
                source="python",
                expected_run_id="run-result",
                label="Python sample",
                event_validator=_validator(EVENT_SCHEMA_PATH),
            )

    @patch("scripts.verify_m0.run")
    @patch("scripts.verify_m0.clear_previous_evidence")
    def test_gate_clears_evidence_before_first_command(self, clear_evidence, run_command) -> None:
        def assert_already_cleared(*_args, **_kwargs) -> None:
            self.assertTrue(clear_evidence.called)

        run_command.side_effect = assert_already_cleared

        self.assertEqual(main(), 0)
        clear_evidence.assert_called_once_with()
        self.assertGreater(run_command.call_count, 0)


if __name__ == "__main__":
    unittest.main()
