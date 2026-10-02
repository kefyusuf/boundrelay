from pathlib import Path
ROOT = Path(__file__).resolve().parents[5]
SCENARIO_PATH = ROOT / 'fixtures/scenarios/support-handoff.yaml'
FAILURE_PATH = ROOT / 'fixtures/failures/support-handoff.yaml'
MODEL_PATH = ROOT / 'fixtures/fake-model/support-handoff.yaml'
EVENT_SCHEMA_PATH = ROOT / 'contracts/events/run-event.schema.json'
RESULT_SCHEMA_PATH = ROOT / 'contracts/results/handoff-result.schema.json'
HANDOFF_SCHEMA_PATH = ROOT / 'contracts/handoffs/support-handoff.schema.json'
ROUTE_SCHEMA_PATH = ROOT / 'contracts/routing/route-decision.schema.json'
