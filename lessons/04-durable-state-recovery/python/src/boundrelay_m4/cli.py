import asyncio,json,sys
from .runner import run_case

def parse_cli_options(args):
    values={};flags=set();required=('--case','--trace','--state-dir');known=required+('--replay-from','--resume')
    index=0
    while index<len(args):
        name=args[index];index+=1
        if name not in known or name in values or name in flags:raise ValueError('Invalid CLI arguments')
        if name=='--resume':flags.add(name);continue
        if index>=len(args) or not args[index] or args[index].startswith('--'):raise ValueError('Invalid CLI arguments')
        values[name]=args[index];index+=1
    if any(name not in values for name in required):raise ValueError('Missing CLI option')
    if '--resume' in flags and '--replay-from' in values:raise ValueError('Resume and replay are mutually exclusive')
    return {'case_id':values['--case'],'trace_path':values['--trace'],'state_dir':values['--state-dir'],'resume':'--resume' in flags,'replay_from':values.get('--replay-from')}

def run_cli(args,stdout=None,stderr=None):
    stdout=stdout or sys.stdout.write;stderr=stderr or sys.stderr.write
    try:stdout(json.dumps(asyncio.run(run_case(**parse_cli_options(args))),allow_nan=False)+'\n');return 0
    except Exception as error:stderr(str(error)+'\n');return 2
