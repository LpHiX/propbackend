from propbackend.state_machine.base_state import State



class IdleState(State):
    def setup(self) -> None:
        self.name = "Idle"

    def loop(self) -> None:
        pass

    def teardown(self) -> None:
        pass

    def can_transition_to(self, target_state) -> tuple[bool, str]:
        from propbackend.state_machine.engine_abort_state import EngineAbortState
        from propbackend.state_machine.fts_state import FTSState
        from propbackend.state_machine.hotfire_state import HotfireState
        from propbackend.state_machine.launch_state import LaunchState
        valid_transitions_anytime = (HotfireState, LaunchState, EngineAbortState, FTSState)
        if isinstance(target_state, valid_transitions_anytime):
            return True, "Valid transition"
        return False, "Invalid transition"