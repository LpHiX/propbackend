from __future__ import annotations
import asyncio

from proppibackend.state_machine.base_state import State
from proppibackend.utils import debug_logger
from proppibackend.utils.time_keeper import TimeKeeper

from proppibackend.state_machine.startup_state import StartupState
from proppibackend.state_machine.idle_state import IdleState
from proppibackend.state_machine.engine_abort_state import EngineAbortState
from proppibackend.state_machine.fts_state import FTSState
from proppibackend.state_machine.hotfire_state import HotfireState
from proppibackend.state_machine.launch_state import LaunchState
from proppibackend.state_machine.hover_state import HoverState





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
        self.time_keeper = TimeKeeper(name="StateMachineTimeKeeper", cycle_time=0.001, debug_time=1)
        self.transition_to(StartupState())

    

    def transition_to(self, state: State) -> None:
        if self._state is not None:
            transition_valid, reason = self._state.can_transition_to(state)
            if not transition_valid:
                debug_logger.debug(f"Attempted transition from {type(self._state).__name__} to {type(state).__name__} failed, Reason: {reason}")
                return
            self._state.teardown()
        debug_logger.info(f"Transitioning from {type(self._state).__name__} to {type(state).__name__}")
        self._state = state
        self._state.state_machine = self
        self._state.setup()
        self.time_keeper.statechange()
        debug_logger.debug(f"State {type(self._state).__name__} setup complete")

    async def main_loop(self) -> None:
        self.time_keeper.cycle_start()
        self._state.loop()
        await self.time_keeper.cycle_end()