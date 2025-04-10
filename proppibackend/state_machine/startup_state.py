from proppibackend.state_machine.base_state import State

import time


class StartupState(State):
    def setup(self) -> None:
        pass

    def loop(self) -> None:
        if self.state_machine.time_keeper.time_since_statechange() > 2:
            self.transition_to_idle()

    def transition_to_idle(self) -> None:
        from proppibackend.state_machine import IdleState
        self.state_machine.transition_to(IdleState())

    def teardown(self) -> None:
        pass

    def can_transition_to(self, target_state: State) -> tuple[bool, str]:
        from proppibackend.state_machine import IdleState, EngineAbortState, FTSState
        valid_transitions_anytime = (IdleState, EngineAbortState, FTSState)
        if isinstance(target_state, valid_transitions_anytime):
            return True, "Valid transition"
        return False, "Invalid transition"