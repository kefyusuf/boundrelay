import argparse
import json
import sys
from collections.abc import Sequence
from typing import cast

from .runner import run_scenario_case
from .types import RunMode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m boundrelay_m0")
    parser.add_argument("--mode", required=True, choices=("deterministic", "model"))
    parser.add_argument("--case", dest="case_id", required=True)
    parser.add_argument("--trace", dest="trace_path", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        options = build_parser().parse_args(argv)
        result = run_scenario_case(
            mode=cast(RunMode, options.mode),
            case_id=options.case_id,
            trace_path=options.trace_path,
        )
        sys.stdout.write(json.dumps(result.to_dict(), separators=(",", ":")) + "\n")
        return 0
    except Exception as error:  # CLI boundary: diagnostics belong on stderr.
        sys.stderr.write(f"{error}\n")
        return 2
