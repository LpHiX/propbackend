from propbackend.state_machine.base_state import State

class HoverState(State):
    def setup(self) -> None:
        self.name = "Hover"

    def loop(self) -> None:
        pass

    def teardown(self) -> None:
        pass