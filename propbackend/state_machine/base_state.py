from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .state_machine import StateMachine

class State(ABC):
    def __init__(self):
        self._state_machine: 'StateMachine' = None

    @property
    def state_machine(self) -> 'StateMachine':
        return self._state_machine

    @state_machine.setter
    def state_machine(self, state_machine: 'StateMachine') -> None:
        self._state_machine = state_machine

    @abstractmethod
    def setup(self) -> None:
        pass

    @abstractmethod
    def loop(self) -> None:
        pass

    @abstractmethod
    def teardown(self) -> None:
        pass

    @abstractmethod
    def can_transition_to(self, target_state: type['State']) -> tuple[bool, str]:
        pass