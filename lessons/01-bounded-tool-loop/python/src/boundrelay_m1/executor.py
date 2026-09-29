import asyncio

from .types import ToolDefinition, ToolName


class ToolTimeoutError(RuntimeError):
    def __init__(self, tool: ToolName) -> None:
        super().__init__(f"Tool timed out: {tool}")
        self.tool=tool


class ToolExecutionError(RuntimeError):
    def __init__(self, tool: ToolName, message: str) -> None:
        super().__init__(message)
        self.tool=tool


async def invoke_tool(definition: ToolDefinition, arguments_value: dict[str, object]) -> dict[str, object]:
    try:
        return await asyncio.wait_for(definition.invoke(arguments_value), timeout=definition.timeout_ms / 1000)
    except TimeoutError as error:
        raise ToolTimeoutError(definition.name) from error
    except Exception as error:
        raise ToolExecutionError(definition.name, str(error)) from error
