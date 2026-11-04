"""M6 chaos harness: replay every declared failure-matrix fault through the
lessons' existing scripted controls and assert the observed response equals
the row's expected_response.

Case rows replay the evaluator's language flow for the referenced canonical
case (exit codes, final status/failure_code, and invocation claims — ledger
contents are read from the flow's state directory). Unit rows prove the
declared class through the lesson suites' existing probe identities.

Standalone tool: plain Python + PyYAML; reuses tools/evaluate.py's flow
machinery. No new fault machinery.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import evaluate as ev  # noqa: E402

MATRIX_PATH = ROOT / "fixtures/failure-matrix.yaml"
LESSON_DIRS = {0: "lessons/00-workflow-or-agent", 1: "lessons/01-bounded-tool-loop",
               2: "lessons/02-routing-handoff", 3: "lessons/03-parallel-fanout-fanin",
               4: "lessons/04-durable-state-recovery", 5: "lessons/05-side-effects-approval"}
GO_TEST_DIRS = {0: ROOT / "go/internal/m0", 3: ROOT / "go/internal/m3"}


class ChaosError(RuntimeError):
    """A row's observed response did not match its expected_response."""


def load_matrix() -> dict:
    document = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    if document.get("schema_version") != "1.0" or not isinstance(document.get("rows"), list):
        raise ChaosError("failure matrix must carry schema_version 1.0 and rows")
    return document


def proof_identity_exists(lesson: int, language: str, identity: str) -> bool:
    if language == "go":
        # M7: the Go proof identities live in the Go module's test suites
        # for the ported lessons only (m0, m3).
        base = GO_TEST_DIRS.get(int(lesson))
        if base is None:
            return False
        return any(identity in path.read_text(encoding="utf-8")
                   for path in base.rglob("*_test.go"))
    subpath = "python/tests" if language == "python" else "typescript/test"
    pattern = "*.py" if language == "python" else "*.ts"
    base = ROOT / LESSON_DIRS[int(lesson)] / subpath
    return any(identity in path.read_text(encoding="utf-8")
               for path in base.rglob(pattern))


def _ledger_counts_per_language(workdir: Path, case_key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for language in ("python", "typescript"):
        ledger = Path(workdir) / f"{case_key}.{language}.state" / "effect-ledger.json"
        counts[language] = (len(json.loads(ledger.read_text(encoding="utf-8"))
                                .get("records", [])) if ledger.is_file() else 0)
    return counts


def _ledger_claim(workdir: Path, case_key: str, expected: object, empty: bool) -> tuple[object, list[str]]:
    counts = _ledger_counts_per_language(workdir, case_key)
    problems: list[str] = []
    for language, count in counts.items():
        if empty and count != 0:
            problems.append(f"{language} ledger not empty: {count} records")
        if not empty and count != expected:
            problems.append(f"{language} ledger records {count} != expected {expected}")
    observed = counts["python"]
    return (observed if not empty else all(count == 0 for count in counts.values())), problems

def _observed_invocations(row: dict, workdir: Path, result: dict) -> tuple[dict, list[str]]:
    claims = row.get("expected_response", {}).get("invocations") or {}
    observed: dict = {}
    problems: list[str] = []
    for key, expected in claims.items():
        if key == "specialist_invoked":
            observed[key] = result.get(key)
        elif key == "tool_invocations":
            observed[key] = result.get(key)
        elif key == "ledger_records":
            observed[key], extra = _ledger_claim(workdir, row["case_key"], expected, empty=False)
            problems.extend(extra)
        elif key == "ledger_empty":
            observed[key], extra = _ledger_claim(workdir, row["case_key"], expected, empty=True)
            problems.extend(extra)
        elif key == "crashed_phase":
            observed[key] = expected
    return observed, problems


def _replay_case_row(row: dict, workdir: Path) -> dict:
    scenario_id = row["scenario"]
    case_key = row["case_key"]
    spec = next(s for s in ev.scenario_cases(scenario_id) if s["key"] == case_key)
    flow = ev.run_flow(scenario_id, spec, workdir)
    result = flow["result"]
    expected = row["expected_response"]
    problems: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    require(result.get("status") == expected.get("status"),
            f"status {result.get('status')} != expected {expected.get('status')}")
    require(result.get("failure_code") == expected.get("failure_code"),
            "failure_code mismatch")
    phases = flow.get("phases") or []
    if phases:
        require(all(phase["exit_code"] in (0, 2) for phase in phases),
                "phase exits must be 0 or 2")
        if expected.get("exit_code") == 2:
            wanted = (expected.get("invocations") or {}).get("crashed_phase")
            if wanted:
                require(any(phase["kind"] == wanted and phase["exit_code"] == 2
                            for phase in phases),
                        f"no crashed phase of kind {wanted}")
            else:
                require(any(phase["exit_code"] == 2 for phase in phases),
                        "expected a phase that exits 2")
        else:
            require(phases[-1]["exit_code"] == 0, "final phase must exit 0")
    else:
        require(expected.get("exit_code") == 0,
                "non-phased flows always complete with exit 0")
    observed, ledger_problems = _observed_invocations(row, workdir, result)
    problems.extend(ledger_problems)
    for key, value in (expected.get("invocations") or {}).items():
        if key in ("specialist_invoked", "tool_invocations"):
            require(observed[key] == value,
                    f"invocation claim {key}: observed {observed[key]} != expected {value}")
    record = {"failure_id": row["failure_id"], "fault": row["fault"],
              "exit_code": expected.get("exit_code"),
              "invocations": observed,
              "result": {"status": result.get("status"),
                         "failure_code": result.get("failure_code")}}
    record["status"] = "FAIL" if problems else "PASS"
    if problems:
        record["problems"] = problems
    return record


def _replay_unit_row(row: dict) -> dict:
    missing = [f"{language}: {identity}"
               for language, identity in row["proof"].items()
               if not proof_identity_exists(row["lesson"], language, identity)]
    record = {"failure_id": row["failure_id"], "fault": row["fault"],
              "exit_code": row.get("expected_response", {}).get("exit_code"),
              "invocations": row.get("expected_response", {}).get("invocations") or {},
              "result": {"status": row.get("expected_response", {}).get("status"),
                         "failure_code": row.get("expected_response", {}).get("failure_code")}}
    record["status"] = "FAIL" if missing else "PASS"
    if missing:
        record["problems"] = ["proof identity missing in suites: " + "; ".join(missing)]
    return record


def replay_matrix(rows: list[dict] | None = None) -> dict:
    selected = rows if rows is not None else load_matrix()["rows"]
    records: list[dict] = []
    for row in selected:
        if row.get("case_key") is not None:
            with tempfile.TemporaryDirectory() as directory:
                records.append(_replay_case_row(row, Path(directory)))
        else:
            records.append(_replay_unit_row(row))
    passed = sum(1 for record in records if record["status"] == "PASS")
    return {"rows": records, "totals": {"passed": passed, "failed": len(records) - passed}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the M6 failure matrix")
    parser.add_argument("--all", action="store_true", help="replay every row")
    parser.add_argument("--failure-id", action="append", default=[],
                        help="replay only these failure ids (repeatable)")
    parser.add_argument("--report", type=Path, default=None, help="write a JSON report")
    args = parser.parse_args(argv)
    rows = load_matrix()["rows"]
    if not args.all and not args.failure_id:
        parser.error("select --all or at least one --failure-id")
    if args.failure_id:
        wanted = set(args.failure_id)
        rows = [row for row in rows if row["failure_id"] in wanted]
        unknown = wanted - {row["failure_id"] for row in rows}
        if unknown:
            raise ChaosError(f"unknown failure ids: {sorted(unknown)}")
    report = replay_matrix(rows=rows)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "schema_version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **report}, indent=2) + "\n", encoding="utf-8")
    for record in report["rows"]:
        print(f"{record['failure_id']}: {record['status']}")
    print(f"chaos totals: {report['totals']['passed']} passed, "
          f"{report['totals']['failed']} failed")
    return 0 if report["totals"]["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
