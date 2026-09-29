from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
SCENARIO_PATH = REPOSITORY_ROOT / "fixtures/scenarios/order-investigation.yaml"
FAKE_MODEL_PATH = REPOSITORY_ROOT / "fixtures/fake-model/order-investigation.yaml"
FAKE_TOOLS_PATH = REPOSITORY_ROOT / "fixtures/fake-tools/order-investigation.yaml"
MODEL_TURN_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/agent/model-turn.schema.json"
LOOKUP_ORDER_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/tools/lookup-order-arguments.schema.json"
LOOKUP_SHIPMENT_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/tools/lookup-shipment-arguments.schema.json"
EVENT_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/events/run-event.schema.json"
RESULT_SCHEMA_PATH = REPOSITORY_ROOT / "contracts/results/tool-loop-result.schema.json"
