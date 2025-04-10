from proppibackend.state_machine import HotfireState
from proppibackend.state_machine import IdleState
from proppibackend.state_machine import StateMachine

def test_state_machine():
    state_machine = StateMachine()
    state_machine.transition_to(IdleState())
    assert isinstance(state_machine._state, IdleState), "State should be IdleState"
    state_machine.transition_to(HotfireState())
    assert isinstance(state_machine._state, HotfireState), "State should be HotfireState"
    state_machine.transition_to(IdleState())
    assert isinstance(state_machine._state, HotfireState), "Transition should have failed"