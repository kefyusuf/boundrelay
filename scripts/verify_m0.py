from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "lessons/00-workflow-or-agent/typescript"
PY_SRC = ROOT / "lessons/00-workflow-or-agent/python/src"
PY_TESTS = ROOT / "lessons/00-workflow-or-agent/python/tests"


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PY_SRC)
    run([sys.executable, "-m", "unittest", "tools.contracts.test_contracts", "-v"])
    run(["npm", "--prefix", str(TS), "run", "typecheck"])
    run(["npm", "--prefix", str(TS), "test"])
    run([sys.executable, "-m", "unittest", "discover", "-s", str(PY_TESTS), "-v"], env)
    run([sys.executable, "-m", "unittest", "tools.parity.test_normalize", "-v"])
    run([sys.executable, "-m", "tools.parity.verify_m0"], env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
