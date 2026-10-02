import asyncio
import json
import sys
from .runner import run_scenario_case


def parse_cli_options(args: list[str]) -> dict[str, str]:
    values = {}
    for index in range(0,len(args),2):
        option = args[index]
        if option not in ('--mode','--case','--trace'): raise ValueError(f'Unexpected argument {option}')
        if option in values: raise ValueError(f'Duplicate option {option}')
        if index+1 >= len(args) or args[index+1].startswith('--'): raise ValueError(f'Missing value {option}')
        values[option] = args[index+1]
    if set(values) != {'--mode','--case','--trace'}: raise ValueError('Required options: --mode --case --trace')
    if values['--mode'] not in ('code','model'): raise ValueError('--mode must be code or model')
    return {'mode': values['--mode'],'case_id': values['--case'],'trace_path': values['--trace']}


def main(args: list[str] | None = None) -> int:
    try:
        options = parse_cli_options(sys.argv[1:] if args is None else args)
        result = asyncio.run(run_scenario_case(**options))
        print(json.dumps(result.to_dict(),separators=(',',':'),allow_nan=False))
        return 0
    except Exception as error:
        print(str(error),file=sys.stderr)
        return 2
