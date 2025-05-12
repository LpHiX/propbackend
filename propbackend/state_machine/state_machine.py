from __future__ import annotations
import asyncio

from propbackend.state_machine.base_state import State
from propbackend.utils import backend_logger
from propbackend.utils.time_keeper import TimeKeeper

from propbackend.state_machine.startup_state import StartupState
from propbackend.state_machine.idle_state import IdleState
from propbackend.state_machine.engine_abort_state import EngineAbortState
from propbackend.state_machine.fts_state import FTSState
from propbackend.state_machine.hotfire_state import HotfireState
from propbackend.state_machine.launch_state import LaunchState
from propbackend.state_machine.hover_state import HoverState

from propbackend.commands.command_processor import CommandProcessor



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
    def __init__(self, command_processor: CommandProcessor) -> None:
        self.command_processor = command_processor

        self._state: State | None = None
        self.time_keeper = TimeKeeper(name="StateMachineTimeKeeper", cycle_time=0.001, debug_time=60)
        self.transition_to(StartupState())

    

    def transition_to(self, state: State) -> str:
        if self._state is not None:
            transition_valid, reason = self._state.can_transition_to(state)
            if not transition_valid:
                reason_string = f"Attempted transition from {type(self._state).__name__} to {type(state).__name__} failed, Reason: {reason}"
                backend_logger.warning(reason_string)
                return reason_string
            self._state.teardown()
        backend_logger.info(f"Transitioning from {type(self._state).__name__} to {type(state).__name__}")
        self._state = state
        self._state.state_machine = self
        self._state.setup()
        self.time_keeper.statechange()
        backend_logger.debug(f"State {type(self._state).__name__} setup complete")
        return f"Transitioned to {type(self._state).__name__}"

    async def main_loop(self) -> None:
        self.time_keeper.cycle_start()
        self._state.loop()
        await self.time_keeper.cycle_end()

    def get_state(self) -> State:
        return self._state