from .policy import ROUTE_RECEIVERS
from .types import ReceiverDefinition, ReceiverDirectory, ReceiverName, ReceiverInput


async def _handle(input: ReceiverInput) -> None:
    pass


def create_receiver_directory(unavailable: tuple[ReceiverName, ...] = ()) -> ReceiverDirectory:
    definitions = {name: ReceiverDefinition(name, _handle) for name in ROUTE_RECEIVERS.values() if name not in unavailable}

    class Directory:
        def resolve(self, name: str): return definitions.get(name)

    return Directory()
