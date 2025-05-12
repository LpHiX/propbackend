from propbackend.state_machine import StartupState
from propbackend.state_machine import StateMachine

def test_state_machine():
    state_machine = StateMachine()

    assert isinstance(state_machine._state, StartupState), "Initial state should be StartupState"
    