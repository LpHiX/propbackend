from proppibackend.state_machine.base_state import State



class IdleState(State):
    def setup(self) -> None:
        pass

    def loop(self) -> None:
        pass

    def teardown(self) -> None:
        pass

    def can_transition_to(self, target_state) -> tuple[bool, str]:
        from proppibackend.state_machine.engine_abort_state import EngineAbortState
        from proppibackend.state_machine.fts_state import FTSState
        from proppibackend.state_machine.hotfire_state import HotfireState
        from proppibackend.state_machine.launch_state import LaunchState
        valid_transitions_anytime = (HotfireState, LaunchState, EngineAbortState, FTSState)
        if isinstance(target_state, valid_transitions_anytime):
            return True, "Valid transition"
        return False, "Invalid transition"