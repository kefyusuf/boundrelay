from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
SCENARIO_PATH = REPOSITORY_ROOT / "fixtures/scenarios/support-handoff.yaml"
FAKE_MODEL_PATH = REPOSITORY_ROOT / "fixtures/fake-model/support-handoff.yaml"
FAILURES_PATH = REPOSITORY_ROOT / "fixtures/failures/support-handoff.yaml"
ROUTE_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/routing/route-decision.schema.json"
HANDOFF_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/handoffs/support-handoff.schema.json"
EVENT_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/events/run-event.schema.json"
RESULT_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/results/handoff-result.schema.json"
