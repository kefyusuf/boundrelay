import asyncio,json,sys
from .runner import run_case

def parse_cli_options(args):
    values={};names=('--mode','--case','--trace')
    if len(args)%2:raise ValueError('Invalid CLI arguments')
    for index in range(0,len(args),2):
        name,value=args[index:index+2]
        if name not in names or name in values or not value or value.startswith('--'):raise ValueError('Invalid CLI arguments')
        values[name]=value
    if set(values)!=set(names) or values['--mode'] not in ('sequential','parallel'):raise ValueError('Missing option or invalid mode')
    return {'mode':values['--mode'],'case_id':values['--case'],'trace_path':values['--trace']}

def run_cli(args,stdout=None,stderr=None):
    stdout=stdout or sys.stdout.write;stderr=stderr or sys.stderr.write
    try:stdout(json.dumps(asyncio.run(run_case(**parse_cli_options(args))),allow_nan=False)+'\n');return 0
    except Exception as error:stderr(str(error)+'\n');return 2
