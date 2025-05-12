from typing import Optional, TYPE_CHECKING, cast
import json
import asyncio
from datetime import datetime

from propbackend.state_machine.hotfire_state import HotfireState
from propbackend.state_machine.engine_abort_state import EngineAbortState
from propbackend.state_machine.idle_state import IdleState
from propbackend.utils import backend_logger
from propbackend.utils import config_reader

if TYPE_CHECKING:
    from propbackend.hardware.hardware_handler import HardwareHandler
    from propbackend.state_machine.state_machine import StateMachine


class CommandProcessor:
    def __init__(self) -> None:
        self._state_machine: Optional["StateMachine"] = None
        self._hardware_handler: Optional["HardwareHandler"] = None
        self.commands = {}
    
    #TODO CHANGE TO COMMAND REGISTERING LATER

    def initialise(self, state_machine: "StateMachine", hardware_handler: "HardwareHandler") -> None:
        self._state_machine = state_machine
        self._hardware_handler = hardware_handler
        self.commands = {
            "get hardware json": self.get_hardware_json,
            # "set hardware json": self.set_hardware_json,
            "reload hardware json": self.reload_hardware_json,
            # "send receive": self.send_receive,
            "get state": self.get_state,
            "update desired state": self.update_desired_state,
            # "disarm all": self.disarm_all,
            # "get hotfire sequence": self.get_hotfire_sequences,
            # "set hotfire sequence": self.set_hotfire_sequences,
            "start hotfire sequence": self.start_hotfire_sequence,
            "abort engine": self.abort_engine,
            "fts": self.fts,
            "get boards states": self.get_boards_states,
            "get boards desired states": self.get_boards_desired_states,
            "get time": self.get_time,
            "return to idle": self.return_to_idle,
        }
    
    @property
    def state_machine(self) -> "StateMachine":
        if self._state_machine is None:
            raise RuntimeError("StateMachine has not been initialised")
        return cast("StateMachine", self._state_machine)

    @property
    def hardware_handler(self) -> "HardwareHandler":
        if self._hardware_handler is None:
            raise RuntimeError("HardwareHandler has not been initialised")
        return cast("HardwareHandler", self._hardware_handler)

    async def process_message(self, command) -> str:
        try:
            message_json = json.loads(command)
        except json.JSONDecodeError:
            backend_logger.error(f"COMMANDPROCESSOR Invalid JSON format: {command}")
            return self.reply_str("Invalid Message", "Invalid JSON format")
        if "command" not in message_json or "data" not in message_json:
            backend_logger.error(f"COMMANDPROCESSOR No command in JSON: {command}")
            return self.reply_str("Invalid Message", "Command not found in message")
        command = message_json["command"]
        data = message_json["data"]
        if command in self.commands:
            func = self.commands[command]
            if asyncio.iscoroutinefunction(func):
                response = await self.commands[command](data)
            else:
                response = func(data)
            return self.reply_str(command, response)
        else:
            backend_logger.error(f"COMMANDPROCESSOR Unknown command: {command}")
            return self.reply_str(command, "Unknown command")

    def get_state(self, _):
        state = self.state_machine.get_state()
        return self.reply_str("get state", state.name)

    def get_time(self, _):
        if self.state_machine.time_keeper is None:
            hotfire_timestr = "TimeKeeperError"
        else:
            hotfire_timestr = "T= Idling"
        state = self.state_machine.get_state()
        if isinstance(state, HotfireState):
            hotfire_time = state.hotfire_controller.get_T(self.state_machine.time_keeper.time_since_statechange())
            if hotfire_time > 0:
                hotfire_timestr = f"T= +{hotfire_time:.2f} s"                
            else:
                hotfire_timestr = f"T= {hotfire_time:.2f} s"
        return self.reply_str("get time",
            {
                "date_time": f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "hotfire_time": hotfire_timestr
            }
        )

    # def get_hotfire_sequences(self, data):
    #     return self.state_machine.hotfirecontroller.get_hotfire_sequence()
    
    # def set_hotfire_sequences(self, data):
    #     return self.state_machine.hotfirecontroller.set_hotfire_sequence(data)
    
    def start_hotfire_sequence(self, data):
        return self.state_machine.transition_to(HotfireState())

    def get_boards_states(self, _):
        states = {}
        for board in self.hardware_handler.boards:
            states[board.name] = board.state
        return json.dumps(states)

    def get_boards_desired_states(self, _):
        desired_states = {}
        for board in self.hardware_handler.boards:
            desired_states[board.name] = board.desired_state
        return json.dumps(desired_states, indent=4)

    def reply_str(self, command, response):
        return json.dumps({"command": command, "response": response})
        
    def update_desired_state(self, data):
        board_name = data["board_name"]
        new_desired_state = data["message"]
        board = self.hardware_handler.get_board(board_name)
        if board is not None:
            board.update_desired_state(new_desired_state)
        return 

    def get_hardware_json(self, _):
        return json.dumps(config_reader.get_config())

    # def set_hardware_json(self, data):
    #     return self.hardware_handler.set_config(data)

    async def reload_hardware_json(self, _):
        self.hardware_handler.unload_hardware()
        config_reader.reload_config()
        await self.hardware_handler.load_hardware()
        return self.reply_str("reload hardware json", "Reloaded hardware json") 

    # async def send_receive(self, data):
    #     try:
    #         board_name = data["board_name"]
    #         message_json = data["message"]
    #         return await self.hardware_handler.send_receive(board_name, message_json)
    #     except KeyError as e:
    #         return f"Missing key in data: {e}"
        

    # def disarm_all(self, _) -> str:
    #     return self.hardware_handler.disarm_all()



        return "stop_task not implemented"
    def abort_engine(self, data):
        return self.state_machine.transition_to(EngineAbortState())
    
    def return_to_idle(self, data):
        return self.state_machine.transition_to(IdleState())

    def fts(self, data):
        print("fts not implemented")
        return "fts not implemented"
        
