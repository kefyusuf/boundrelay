"""Deterministic attribution for M3 runs: fixture-priced, clock-injected."""

STEP_KINDS=('read','model_decision','tool_call','effect','handoff','route','synthesis')

def step_kind(step_name):
    if step_name=='synthesize':return 'synthesis'
    if step_name.startswith('worker.'):return 'read'
    raise ValueError(f'Unknown attribution step: {step_name}')

def build_attribution(step_records,price_table,latency_table):
    steps=[];totals={'latency_ms':0,'cost_cents':0,'attempts':0}
    for step_name,attempts in step_records:
        if type(attempts) is not int or attempts<1:raise ValueError(f'Invalid attribution attempts for {step_name}')
        if step_name not in latency_table:raise ValueError(f'Unknown attribution step: {step_name}')
        kind=step_kind(step_name)
        if kind not in price_table:raise ValueError(f'Unknown attribution price kind: {kind}')
        record={'step_name':step_name,'latency_ms':latency_table[step_name]*attempts,'cost_cents':price_table[kind]*attempts,'attempts':attempts}
        steps.append(record)
        totals['latency_ms']+=record['latency_ms'];totals['cost_cents']+=record['cost_cents'];totals['attempts']+=attempts
    if not steps:raise ValueError('Attribution requires at least one executed step')
    return {'steps':steps,'totals':totals}
