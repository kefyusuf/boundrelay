import argparse
import asyncio
from dataclasses import dataclass
import json
import sys
from collections.abc import Sequence
from typing import TextIO, cast

from .runner import run_scenario_case
from .types import RunMode


@dataclass(frozen=True)
class CliOptions:
    mode: RunMode
    case_id: str
    trace_path: str


class StrictArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = StrictArgumentParser(prog="python -m boundrelay_m1", add_help=False)
    parser.add_argument("--mode", required=True, choices=("direct", "agent"))
    parser.add_argument("--case", dest="case_id", required=True)
    parser.add_argument("--trace", dest="trace_path", required=True)
    return parser


def parse_cli_options(argv: Sequence[str]) -> CliOptions:
    allowed={"--mode","--case","--trace"}
    seen: set[str]=set()
    values=list(argv)
    index=0
    while index < len(values):
        option=values[index]
        if option not in allowed:
            raise ValueError(f"Unexpected argument {option}")
        if option in seen:
            raise ValueError(f"Duplicate option {option}")
        if index+1 >= len(values) or values[index+1].startswith("--"):
            raise ValueError(f"Missing required option {option}")
        seen.add(option); index+=2
    parsed=build_parser().parse_args(values)
    return CliOptions(cast(RunMode,parsed.mode),parsed.case_id,parsed.trace_path)


def main(argv: Sequence[str] | None = None, *, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out=stdout or sys.stdout
    err=stderr or sys.stderr
    try:
        options=parse_cli_options(list(argv) if argv is not None else sys.argv[1:])
        result=asyncio.run(run_scenario_case(mode=options.mode,case_id=options.case_id,trace_path=options.trace_path))
        out.write(json.dumps(result.to_dict(),separators=(",",":"),allow_nan=False)+"\n")
        return 0
    except Exception as error:
        err.write(f"{error}\n")
        return 2
