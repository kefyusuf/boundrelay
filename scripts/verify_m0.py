from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "lessons/00-workflow-or-agent/typescript"
PY_SRC = ROOT / "lessons/00-workflow-or-agent/python/src"
PY_TESTS = ROOT / "lessons/00-workflow-or-agent/python/tests"
OUTPUT_ROOT = ROOT / ".boundrelay/m0"


def clear_previous_evidence(output_root: Path = OUTPUT_ROOT) -> None:
    shutil.rmtree(output_root, ignore_errors=True)


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    clear_previous_evidence()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PY_SRC)
    run([sys.executable, "-m", "unittest", "tools.contracts.test_contracts", "-v"])
    run(["npm", "--prefix", str(TS), "run", "typecheck"])
    run(["npm", "--prefix", str(TS), "test"])
    run([sys.executable, "-m", "unittest", "discover", "-s", str(PY_TESTS), "-v"], env)
    run([
        sys.executable,
        "-m",
        "unittest",
        "tools.parity.test_normalize",
        "tools.parity.test_verification_safety",
        "tools.parity.test_trace_contract",
        "tools.parity.test_rejection_contract",
        "-v",
    ])
    run([sys.executable, "-m", "tools.parity.verify_m0"], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
