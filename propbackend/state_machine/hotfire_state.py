from propbackend.state_machine.base_state import State



from propbackend.controllers.hotfire_controller import HotfireController

class HotfireState(State):
    def setup(self) -> None:
        self.hotfire_controller = HotfireController()

    def loop(self) -> None:
        pass

    def teardown(self) -> None:
        pass

    def can_transition_to(self, target_state) -> tuple[bool, str]:
        from propbackend.state_machine.idle_state import IdleState
        from propbackend.state_machine.engine_abort_state import EngineAbortState

        valid_transitions_anytime = (EngineAbortState)
        if isinstance(target_state, valid_transitions_anytime):
            return True, "Valid transition"
        if isinstance(target_state, IdleState):
            if self.hotfire_controller.is_hotfire_complete():
                return True, "Valid transition"
            else:
                return False, "Hotfire not complete"
        return False, "Invalid transition"