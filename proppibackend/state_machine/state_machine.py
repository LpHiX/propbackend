from __future__ import annotations
from .base_state import State

from .states.startup_state import StartupState
from .states.idle_state import IdleState
from .states.engine_abort_state import EngineAbortState
from .states.fts_state import FTSState
from .states.hotfire_state import HotfireState
from .states.launch_state import LaunchState
from .states.hover_state import HoverState

from ..utils import debug_logger




class StateMachine:
    _valid_transitions= {
        StartupState: {IdleState, EngineAbortState, FTSState},
        IdleState: {HotfireState, LaunchState, EngineAbortState, FTSState},
        EngineAbortState: {IdleState, FTSState},
        FTSState: {IdleState},
        HotfireState: {IdleState, EngineAbortState, FTSState},
        LaunchState: {HoverState, EngineAbortState, FTSState},
        HoverState: {IdleState, EngineAbortState, FTSState},
    }
    def __init__(self) -> None:
        self._state: State | None = None
        self.transition_to(StartupState())
        #self.hotfirecontroller = self.HotfireController()

    def transition_to(self, state: State) -> None:
        if not self.is_valid_transition(type(state)):
            debug_logger.debug(f"Invalid transition from {type(self._state).__name__} to {type(state).__name__}. Allowed = {[s.__name__ for s in self._valid_transitions.get(type(self._state), set())]}")
        if self._state is not None:
            self._state.teardown()
        self._state = state
        self._state.state_machine = self
        self._state.setup()

    def is_valid_transition(self, target_state: type[State]) -> bool:
        if self._state is None:
            return True
        return target_state in self._valid_transitions.get(type(self._state), set())