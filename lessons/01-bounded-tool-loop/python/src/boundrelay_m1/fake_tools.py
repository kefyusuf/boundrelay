import asyncio
from copy import deepcopy
from pathlib import Path
from typing import Mapping

import yaml

from .paths import FAKE_TOOLS_PATH


def _load_fake_tools(path: Path = FAKE_TOOLS_PATH) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if (
        not isinstance(document, Mapping)
        or document.get("schema_version") != "1.0"
        or document.get("scenario_id") != "order-investigation"
    ):
        raise ValueError("Unsupported M1 fake-tool fixture.")
    orders = document.get("orders")
    shipments = document.get("shipments")
    if not isinstance(orders, Mapping) or not isinstance(shipments, Mapping):
        raise ValueError("Fake-tool fixture must define orders and shipments.")

    def parse_records(raw: Mapping[object, object], label: str) -> dict[str, dict[str, object]]:
        parsed: dict[str, dict[str, object]] = {}
        for identifier, entry in raw.items():
            if not isinstance(identifier, str) or not isinstance(entry, Mapping):
                raise ValueError(f"{label} {identifier} must be an object.")
            parsed[identifier] = deepcopy(dict(entry))
        return parsed

    return parse_records(orders, "Order"), parse_records(shipments, "Shipment")


_ORDERS, _SHIPMENTS = _load_fake_tools()


async def _invoke_entry(entry: dict[str, object], label: str) -> dict[str, object]:
    if entry.get("behavior") == "timeout":
        await asyncio.Future()
        raise AssertionError("unreachable")
    if entry.get("behavior") == "failure":
        raise RuntimeError(f"{label} scripted failure.")
    output = entry.get("output")
    if not isinstance(output, Mapping):
        raise ValueError(f"{label} fixture must contain output or behavior.")
    return deepcopy(dict(output))


async def lookup_order(arguments_value: dict[str, object]) -> dict[str, object]:
    order_id = arguments_value.get("order_id")
    if not isinstance(order_id, str) or order_id not in _ORDERS:
        raise ValueError(f"Unknown order fixture: {order_id}")
    return await _invoke_entry(_ORDERS[order_id], f"Order {order_id}")


async def lookup_shipment(arguments_value: dict[str, object]) -> dict[str, object]:
    shipment_id = arguments_value.get("shipment_id")
    if not isinstance(shipment_id, str) or shipment_id not in _SHIPMENTS:
        raise ValueError(f"Unknown shipment fixture: {shipment_id}")
    return await _invoke_entry(_SHIPMENTS[shipment_id], f"Shipment {shipment_id}")
