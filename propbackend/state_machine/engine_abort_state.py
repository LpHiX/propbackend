from .base_state import State
from propbackend.controllers.hotfire_controller import HotfireController
from propbackend.utils import backend_logger


class EngineAbortState(State):
    def setup(self) -> None:
        self.name = "Engine Abort"
        self.hotfire_controller = HotfireController()

    def loop(self) -> None:
        board_desired_state = self.hotfire_controller.get_abort_desiredstate()
        for board_name, desired_state in board_desired_state.items():
            board = self.state_machine.hardware_handler.get_board(board_name)   
            if board:
                board.update_desired_state(desired_state)
            else:
                backend_logger.warning(f"Board {board_name} not found in hotfire state")
                # -----------------------------------
                #TODO SHOULD THIS TRIGGER AN ABORT?
                # ----------------------------------


    def teardown(self) -> None:
        pass

    def can_transition_to(self, target_state) -> tuple[bool, str]:
        from propbackend.state_machine.idle_state import IdleState
        from propbackend.state_machine.fts_state import FTSState
        valid_transitions_anytime = (FTSState)
        if isinstance(target_state, valid_transitions_anytime):
            return True, "Valid transition"
        if isinstance(target_state, IdleState):
            time_since_statechange = self.state_machine.time_keeper.time_since_statechange()
            if time_since_statechange > 2:
                return True, "Valid transition"
            else:
                return False, f"Cannot return to IDLE, only {time_since_statechange} seconds passed"
        return False, "Invalid transition"