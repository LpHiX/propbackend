from propbackend.state_machine.base_state import State

class LaunchState(State):
    
    def setup(self) -> None:
        self.name = "Launch"

    def loop(self) -> None:
        pass

    def teardown(self) -> None:
        pass