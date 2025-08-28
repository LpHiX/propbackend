from propbackend.state_machine.base_state import State
from propbackend.utils import backend_logger
from propbackend.utils.boardstate_logger import BoardStateLogger



from propbackend.controllers.hotfire_controller import HotfireController

class HotfireState(State):
    def setup(self) -> None:
        self.name = "Hotfire"
        self.hotfire_controller = HotfireController()

        self.hotfire_logger = BoardStateLogger("HotfireLog", self.state_machine.hardware_handler)
        self.hotfire_logger.write_headers(self.state_machine.hardware_handler.boards)

    def loop(self) -> None:
        time_keeper = self.state_machine.time_keeper
        time_statechange = time_keeper.time_since_statechange()

        T = self.hotfire_controller.get_T(time_statechange)
        
        if time_keeper.get_cycle() % 100 == 0:
            backend_logger.info(f"T{T:.0f}s")

        board_desired_state = self.hotfire_controller.get_hotfire_desiredstate(time_statechange)

        for board_name, desired_state in board_desired_state.items():
            board = self.state_machine.hardware_handler.get_board(board_name)   
            if board:
                board.update_desired_state(desired_state)
            else:
                backend_logger.warning(f"Board {board_name} not found in hotfire state")
                # -----------------------------------
                #TODO SHOULD THIS TRIGGER AN ABORT?
                # ----------------------------------

        self.hotfire_logger.write_data(self.state_machine.hardware_handler.boards)
        
        if self.hotfire_controller.is_hotfire_complete(time_statechange):
            backend_logger.info(f"Hotfire complete at T{T:.0f}s")
            self.hotfire_logger.close()
            

            from propbackend.state_machine.idle_state import IdleState
            self.state_machine.transition_to(IdleState())

    def teardown(self) -> None:
        pass

    def can_transition_to(self, target_state) -> tuple[bool, str]:
        from propbackend.state_machine.idle_state import IdleState
        from propbackend.state_machine.engine_abort_state import EngineAbortState

        valid_transitions_anytime = (EngineAbortState)
        if isinstance(target_state, valid_transitions_anytime):
            return True, "Valid transition"
        if isinstance(target_state, IdleState):
            if self.hotfire_controller.is_hotfire_complete(self.state_machine.time_keeper.time_since_statechange()):
                return True, "Valid transition"
            else:
                return False, "Hotfire not complete"
        return False, "Invalid transition"