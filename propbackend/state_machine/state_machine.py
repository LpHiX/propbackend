from __future__ import annotations
import asyncio
from typing import TYPE_CHECKING
from datetime import datetime, timezone
import time

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

from propbackend.hardware.hardware_handler import HardwareHandler

if TYPE_CHECKING:
    from propbackend.utils.boardstate_logger import BoardStateLogger



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
    def __init__(self, hardware_handler: HardwareHandler) -> None:
        self.hardware_handler = hardware_handler

        self._state: State | None = None
        self.active_run_logger: BoardStateLogger | None = None
        self.active_run_time_offset: float | None = None
        self.main_loop_logger: BoardStateLogger | None = None
        self.timer_t0_unix_ms: int = 0
        self.timer_t0_mono_ms: int = 0
        self.time_keeper = TimeKeeper(name="StateMachineTimeKeeper", cycle_time=0.01, debug_time=60)
        self.transition_to(StartupState())

    

    def transition_to(self, state: State) -> str:
        previous_state = self._state
        previous_name = type(self._state).__name__ if self._state is not None else "None"
        target_name = type(state).__name__

        if isinstance(previous_state, HotfireState) and isinstance(state, EngineAbortState):
            if self.time_keeper is not None:
                time_statechange = self.time_keeper.time_since_statechange()
                self.active_run_time_offset = previous_state.hotfire_controller.get_T(time_statechange)
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

        if isinstance(state, HotfireState):
            self.active_run_time_offset = None
            self._set_timer_payload_for_all(elapsed=True, reset_start=True)
        elif isinstance(state, EngineAbortState):
            self._set_timer_payload_for_all(elapsed=False, reset_start=False)
        elif isinstance(state, IdleState):
            self._set_timer_payload_for_all(elapsed=False, reset_start=False)
        else:
            self._set_timer_payload_for_all(elapsed=False, reset_start=False)

        if self.active_run_logger is not None:
            self.active_run_logger.log_event(
                event_type="state_transition",
                source="state_machine",
                target=target_name,
                message=f"{previous_name}->{target_name}",
            )

        # Keep run logger active through abort and close only once we return to Idle.
        if isinstance(state, IdleState) and isinstance(previous_state, (HotfireState, EngineAbortState)):
            if self.active_run_logger is not None:
                self.active_run_logger.close()
                self.active_run_logger = None
            self.active_run_time_offset = None

        self.time_keeper.statechange()
        backend_logger.debug(f"State {type(self._state).__name__} setup complete")
        return f"Transitioned to {type(self._state).__name__}"

    async def main_loop(self) -> None:
        self.time_keeper.cycle_start()
        if self._state is not None:
            self._state.loop()
        else:
            backend_logger.error("State machine is not initialized")
        await self.time_keeper.cycle_end()

    def get_state(self) -> State:
        assert self._state is not None, "StateMachine has no state"
        return self._state

    def _set_timer_payload_for_all(self, elapsed: bool, reset_start: bool) -> None:
        if reset_start:
            self.timer_t0_unix_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
            self.timer_t0_mono_ms = int(time.perf_counter() * 1000)

        for board in self.hardware_handler.boards:
            if "timer" not in board.board_config:
                continue

            board.desired_state["t0_unix_ms"] = self.timer_t0_unix_ms
            board.desired_state["t0_mono_ms"] = self.timer_t0_mono_ms
            board.desired_state["elapsed"] = elapsed