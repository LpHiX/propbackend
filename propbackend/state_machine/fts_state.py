from propbackend.state_machine.base_state import State


class FTSState(State):
    def setup(self) -> None:
        self.name = "FTS"

    def loop(self) -> None:
        pass

    def teardown(self) -> None:
        pass

    def can_transition_to(self, target_state) -> tuple[bool, str]:
        from propbackend.state_machine.idle_state import IdleState
        valid_transitions_anytime = (IdleState)
        if isinstance(target_state, valid_transitions_anytime):
            return True, "Valid transition"
        return False, "Invalid transition"