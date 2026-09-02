from copy import deepcopy

from .types import SpecialistInvocation


class RecordingSpecialistDispatcher:
    def __init__(self) -> None:
        self._invocations: list[SpecialistInvocation] = []

    @property
    def invocations(self) -> tuple[SpecialistInvocation, ...]:
        return tuple(deepcopy(self._invocations))

    def dispatch(self, invocation: SpecialistInvocation) -> None:
        self._invocations.append(deepcopy(invocation))
