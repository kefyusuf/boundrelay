from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
SCENARIO_PATH = REPOSITORY_ROOT / "fixtures/scenarios/support-triage.yaml"
FAKE_MODEL_PATH = REPOSITORY_ROOT / "fixtures/fake-model/support-triage.yaml"
ROUTE_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/routing/route-decision.schema.json"
EVENT_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/events/run-event.schema.json"
RESULT_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/results/run-result.schema.json"
