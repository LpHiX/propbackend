from typing import TYPE_CHECKING
import json


if TYPE_CHECKING:
    from propbackend.hardware.hardware_handler import HardwareHandler
    from propbackend.state_machine.state_machine import StateMachine


class CommandProcessor:
    def __init__(self) -> None:
        self.state_machine = None
        self.hardware_handler = None
        self.commands = {}
    
    #TODO CHANGE TO COMMAND REGISTERING LATER

    def initialise(self, state_machine: "StateMachine", hardware_handler: "HardwareHandler") -> None:
        self.state_machine = state_machine
        self.hardware_handler = hardware_handler
        self.commands = {
            "get hardware json": self.get_hardware_json,
            "set hardware json": self.set_hardware_json,
            "reload hardware json": self.reload_hardware_json,
            "send receive": self.send_receive,
            #"set state": self.set_state,
            "get state": self.get_state,
            "get startup tasks": self.get_startup_tasks,
            "update desired state": self.update_desired_state,
            "get running tasks": self.get_running_tasks,
            "add and run task": self.add_and_run_task,
            "stop task": self.stop_task,
            "disarm all": self.disarm_all,
            "get hotfire sequence": self.get_hotfire_sequences,
            "set hotfire sequence": self.set_hotfire_sequences,
            "start hotfire sequence": self.start_hotfire_sequence,
            "abort engine": self.abort_engine,
            "fts": self.fts,
            "get boards states": self.get_boards_states,
            "get boards desired states": self.get_boards_desired_states,
            "get time": self.get_time,
            "return to idle": self.return_to_idle,
        }

    def get_state(self, _):
        state = self.state_machine.get_state()
        return self.reply_str("get state", state.name)

    def get_time(self, _):
        if self.state_machine.time_keeper is None:
            hotfire_timestr = "TimeKeeperError"
        else:
            hotfire_timestr = "T= Idling"
        if self.state_machine.get_state() == MachineStates.HOTFIRE:
            hotfire_time = self.state_machine.hotfirecontroller.get_T(self.state_machine.time_keeper.time_since_statechange())
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

    def get_hotfire_sequences(self, data):
        return self.state_machine.hotfirecontroller.get_hotfire_sequence()
    
    def set_hotfire_sequences(self, data):
        return self.state_machine.hotfirecontroller.set_hotfire_sequence(data)
    
    def start_hotfire_sequence(self, data):
        return self.state_machine.start_hotfire()

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
    
    async def process_message(self, command):
        try:
            message_json = json.loads(command)
        except json.JSONDecodeError:
            print(f"Invalid JSON format: {command}")
            return self.reply_str("Invalid Message", "Invalid JSON format")
        if "command" not in message_json or "data" not in message_json:
            print(f"No command found: {command}")
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
            print(f"Unknown command: {command}")
            return self.reply_str(command, "Unknown command")
        
    def update_desired_state(self, data):
        print("command recieved")
        board_name = data["board_name"]
        new_desired_state = data["message"]
        return self.hardware_handler.update_board_desired_state(board_name, new_desired_state)

    def get_hardware_json(self, _):
        return json.dumps(self.hardware_handler.get_config())
    
    def set_hardware_json(self, data):
        return self.hardware_handler.set_config(data)

    async def reload_hardware_json(self, _):
        result = await self.hardware_handler.reload_config()
        if hasattr(self, 'recurring_task_handler'):
            self.recurring_task_handler.on_machine_startup()
        return result

    async def send_receive(self, data):
        try:
            board_name = data["board_name"]
            message_json = data["message"]
            return await self.hardware_handler.send_receive(board_name, message_json)
        except KeyError as e:
            return f"Missing key in data: {e}"
    def set_recurring_task_handler(self, recurring_task_handler):
        self.recurring_task_handler = recurring_task_handler
    def get_startup_tasks(self, _):
        return self.hardware_handler.get_startup_tasks(self)

    def disarm_all(self, _) -> str:
        return self.hardware_handler.disarm_all()

    def get_running_tasks(self, _):
        print("get_running_tasks not implemented")
        return "get_running_tasks not implemented"
    def add_and_run_task(self, data):
        print("add_and_run_task not implemented")
        return "add_and_run_task not implemented"
    def stop_task(self, data):
        print("stop_task not implemented")
        return "stop_task not implemented"
    def abort_engine(self, data):
        return self.state_machine.abort_engine()
    
    def return_to_idle(self, data):
        time_since_statechange = self.state_machine.time_keeper.time_since_statechange()
        if self.state_machine.get_state() == MachineStates.IDLE:
            return self.reply_str("return to idle", "Already in IDLE state")
        if self.state_machine.get_state() == MachineStates.STARTTUP:
            return self.reply_str("return to idle", "Cannot return to IDLE from STARTUP state")
        if self.state_machine.get_state() == MachineStates.HOTFIRE:
            return self.reply_str("return to idle", "Cannot return to IDLE from HOTFIRE state, use abort")
        if self.state_machine.get_state() == MachineStates.ENGINEABORT:
            if self.state_machine.time_keeper.time_since_statechange() < 2.0:
                return self.reply_str("return to idle", f"Cannot return to IDLE only {time_since_statechange} seconds after abort")
            else:
                self.state_machine.set_state(MachineStates.IDLE)
                self.state_machine.time_keeper.statechange()
                self.hardware_handler.disarm_all()
                return self.reply_str("return to idle", "Returned to IDLE state")

    def fts(self, data):
        print("fts not implemented")
        return "fts not implemented"
        
