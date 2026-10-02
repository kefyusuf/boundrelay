from pathlib import Path
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
M1_TS = ROOT / "lessons/01-bounded-tool-loop/typescript"
M1_PY_SRC = ROOT / "lessons/01-bounded-tool-loop/python/src"
M1_PY_TESTS = ROOT / "lessons/01-bounded-tool-loop/python/tests"
OUTPUT_ROOT = ROOT / ".boundrelay/m1"


def clear_previous_evidence(output_root: Path = OUTPUT_ROOT) -> None:
    shutil.rmtree(output_root, ignore_errors=True)


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run([shutil.which(command[0]) or command[0], *command[1:]], cwd=ROOT, env=env, check=True)


def main() -> int:
    clear_previous_evidence()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(M1_PY_SRC)
    run([sys.executable, "scripts/verify_m0.py"])
    run([sys.executable, "-m", "unittest", "tools.contracts.test_m1_contracts", "-v"], env)
    run(["npm", "--prefix", str(M1_TS), "run", "typecheck"])
    run(["npm", "--prefix", str(M1_TS), "test"])
    run([sys.executable, "-m", "unittest", "discover", "-s", str(M1_PY_TESTS), "-v"], env)
    run([
        sys.executable, "-m", "unittest",
        "tools.parity.test_normalize",
        "tools.parity.test_trace_contract",
        "tools.parity.test_m1_verification_safety",
        "-v",
    ], env)
    run([sys.executable, "-m", "tools.parity.verify_m1"], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
