"""M8 mapping CLI: --case <id> [--mode naive|corrected] --trace <file>.

Prints exactly one JSON result line on stdout and exits 0 for every
domain result (SUCCEEDED, PARTIAL, FAILED). Tooling failures - unknown
or missing options, unknown case, naive-mode default propagation -
print to stderr and exit 2 without a canonical result.
"""
import json
import sys

from .graph import run_corrected
from .naive import run_naive

VALID_MODES = ("naive", "corrected")
DEFAULT_MODE = "corrected"


def parse_cli_options(args):
    values = {}
    names = ("--mode", "--case", "--trace")
    if len(args) % 2:
        raise ValueError("Invalid CLI arguments")
    for index in range(0, len(args), 2):
        name, value = args[index:index + 2]
        if (name not in names or name in values or type(value) is not str
                or not value or value.startswith("--")):
            raise ValueError("Invalid CLI arguments")
        values[name] = value
    if "--case" not in values or "--trace" not in values:
        raise ValueError("Missing --case or --trace")
    mode = values.get("--mode", DEFAULT_MODE)
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mode: {mode}")
    return {"mode": mode, "case_id": values["--case"],
            "trace_path": values["--trace"]}


def run_cli(args, stdout=None, stderr=None):
    stdout = stdout or sys.stdout.write
    stderr = stderr or sys.stderr.write
    try:
        options = parse_cli_options(list(args))
        runner = run_naive if options["mode"] == "naive" else run_corrected
        result = runner(options["case_id"], options["trace_path"])
        stdout(json.dumps(result, ensure_ascii=True, allow_nan=False) + "\n")
        return 0
    except Exception as error:
        stderr(f"{type(error).__name__}: {error}\n")
        return 2


def main(argv=None):
    return run_cli(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
