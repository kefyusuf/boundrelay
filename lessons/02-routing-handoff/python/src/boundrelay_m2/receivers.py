from .types import RECEIVER_NAMES, ReceiverDefinition, ReceiverDirectory, ReceiverInput, ReceiverName


class StaticReceiverDirectory(ReceiverDirectory):
    def __init__(self, definitions: tuple[ReceiverDefinition, ...]) -> None:
        self._definitions = {definition.name: definition for definition in definitions}

    def resolve(self, name: str) -> ReceiverDefinition | None:
        return self._definitions.get(name)


async def _handle_noop(input_value: ReceiverInput) -> None:
    del input_value


def _receiver(name: ReceiverName) -> ReceiverDefinition:
    return ReceiverDefinition(name=name, handle=_handle_noop)


def create_receiver_directory(
    unavailable: tuple[ReceiverName, ...] = (),
) -> ReceiverDirectory:
    unavailable_set = set(unavailable)
    return StaticReceiverDirectory(
        tuple(_receiver(name) for name in RECEIVER_NAMES if name not in unavailable_set)
    )
