from .base_state import State



class EngineAbortState(State):
    def setup(self) -> None:
        pass

    def loop(self) -> None:
        pass

    def teardown(self) -> None:
        pass

    def can_transition_to(self, target_state) -> tuple[bool, str]:
        from propbackend.state_machine.idle_state import IdleState
        from propbackend.state_machine.fts_state import FTSState
        valid_transitions_anytime = (IdleState, FTSState)
        if isinstance(target_state, valid_transitions_anytime):
            return True, "Valid transition"
        return False, "Invalid transition"