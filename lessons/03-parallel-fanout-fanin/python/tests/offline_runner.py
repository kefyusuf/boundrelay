import asyncio,json,runpy,socket,tempfile
from pathlib import Path
async def main():
    # Initialize the event loop before blocking Windows' socketpair setup.
    original=socket.socket.connect
    def blocked(*args,**kwargs):raise RuntimeError('network denied')
    def connect(sock,*args,**kwargs):
        if sock.family in (socket.AF_INET,socket.AF_INET6):return blocked()
        return original(sock,*args,**kwargs)
    socket.create_connection=blocked;socket.socket.connect=connect;socket.socket.connect_ex=connect
    try:runpy.run_path(str(Path(__file__).with_name('offline_import_probe.py')))
    except RuntimeError as error:
        if str(error)!='network denied':raise
    else:raise AssertionError('Import guard missing')
    from boundrelay_m3.runner import run_case
    from boundrelay_m3.scenario import load_scenario
    statuses=[]
    with tempfile.TemporaryDirectory() as tmp:
        for c in load_scenario().cases:
            result=await run_case(case_id=c.case_id,mode=c.execution_mode,trace_path=str(Path(tmp)/(c.case_id+'.jsonl')))
            statuses.append(result['status'])
    print(json.dumps({'import_probe_blocked':True,'statuses':statuses}))
asyncio.run(main())
