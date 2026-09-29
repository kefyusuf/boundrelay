from collections.abc import Awaitable, Callable

from .fake_tools import lookup_order, lookup_shipment
from .schemas import validate_tool_arguments
from .types import ToolDefinition, ToolName, ToolRegistry, ValidationResult


class StaticToolRegistry(ToolRegistry):
    def __init__(self, definitions: tuple[ToolDefinition, ...]) -> None:
        self._definitions = {definition.name: definition for definition in definitions}

    def resolve(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)


def _definition(
    name: ToolName,
    invoke: Callable[[dict[str, object]], Awaitable[dict[str, object]]],
) -> ToolDefinition:
    def validate(value: object) -> ValidationResult[dict[str, object]]:
        return validate_tool_arguments(name, value)

    return ToolDefinition(
        name=name,
        side_effect="READ_ONLY",
        timeout_ms=100,
        validate_arguments=validate,
        invoke=invoke,
    )


def create_fake_tool_registry() -> ToolRegistry:
    return StaticToolRegistry((
        _definition("lookup_order", lookup_order),
        _definition("lookup_shipment", lookup_shipment),
    ))
