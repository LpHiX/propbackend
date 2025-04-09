import json
from .board import Board
from ..serial_manager.serial_manager import SerialManager
import copy

class HardwareHandler:
    def __init__(self, emulator: bool = False, debug_prints: bool = False):
        self.emulator: bool = emulator
        self.debug_prints: bool = debug_prints
        self.boards: list[Board] = []
        self.state_defaults: dict = {}
        self.hardware_types: list[str] = []
     
    async def initialize(self):
        """Initialize all hardware asynchronously"""
        return await self.load_hardware()
    
    async def load_hardware(self):

        with open('hardware_config.json', 'r') as file:
            self.config = json.load(file)
        with open('hardware_config.json', 'w') as file:
                json.dump(self.config, file, indent=4)
        # Initialize serial managers for each board in the configuration
        if 'boards' not in self.config:
            print("No boards found in configuration, json error")
            return
        if 'state_defaults' not in self.config:
            print("No state defaults found in configuration, json error")
            return
        self.state_defaults: dict = self.config['state_defaults']
        self.hardware_types = list(self.state_defaults.keys())
        
        for board_name, board_config in self.config['boards'].items():
            serial_config = board_config['serial']

            serial_manager = None
            state = {"updated": False}

            if 'port' in serial_config and 'baudrate' in serial_config:
                try:
                    serial_manager = SerialManager(
                        board_name,
                        port=serial_config['port'],
                        baudrate=serial_config['baudrate'],
                        #print_send=self.debug_prints,
                        #print_receive=self.debug_prints,
                        emulator=self.emulator
                    )
                    if await serial_manager.initialize():                        
                        print(f"Initialized serial connection for board: {board_name}")
                except Exception as e:
                    print(f"Failed to initialize serial for board {board_name}: {e}")
            else:
                print(f"Board {board_name} is missing port or baudrate configuration")

            for hw_type in self.hardware_types:
                if hw_type in board_config:
                    state[hw_type] = {}
                    for item_name, item_data in board_config[hw_type].items():
                        state[hw_type][item_name] = {**self.state_defaults[hw_type].copy(), **item_data}
            is_actuator = board_config.get('is_actuator', False)
            if is_actuator:
                desired_state = copy.deepcopy(state) # WHAT THE FUCK, NESTED DICTIONARIES WERE STILL REFERENCE BASED, LEADING TO UPDATING DESIRED STATES UPDATING ACTUAL STATES
                if "servos" in board_config:
                    desired_state["servos"] = {}
                    for servo_name, servo_data in board_config["servos"].items():
                        desired_state["servos"][servo_name] = {"channel": servo_data['channel'], "armed": False}
                        if 'safe_angle' in servo_data:
                            desired_state["servos"][servo_name]["armed"] = True
                            desired_state["servos"][servo_name]["angle"] = servo_data['safe_angle']
                self.boards.append(Board(board_name, serial_manager, state, board_config, desired_state))
            else:
                self.boards.append(Board(board_name, serial_manager, state, board_config))
    
    def get_board(self, board_name):
        """Get a board by name"""
        for board in self.boards:
            if board.name == board_name:
                return board
        return None

    def update_board_state(self, board_name, new_state):
        board = self.get_board(board_name)
        if not board:
            print(f"Board {board_name} not found")
            return
        
        for hw_type in self.hardware_types:
            if hw_type in new_state and hw_type in board.state:
                for item_name, item_data in new_state[hw_type].items():
                    if item_name in board.state[hw_type]:
                        for key, value in item_data.items():
                            board.state[hw_type][item_name][key] = value

    def generate_command(self, command:str, board_name:str, desired_state:dict) -> dict:
        return {
            "command": command,
            "data":
            {
                "board_name": board_name,
                "message": desired_state
            }
        }
    def get_startup_tasks(self, command_processor):
        """Get startup tasks from the hardware configuration"""
        startup_tasks = []
        for board in self.boards:
            board_name = board.name
            board_config = board.config
            if not board:
                print(f"Board {board_name} not found in config loaded boards")
                continue
            if not board.is_actuator:
                message = {"timestamp": 0}
                for hw_type in self.hardware_types:
                    if hw_type in board.state:
                        message[hw_type] = {}
                        for item_name, item_data in board.state[hw_type].items():
                            message[hw_type][item_name] = {"channel": item_data['channel']}
                startup_command = self.generate_command("send receive", board_name, message)
            else:
                startup_command = self.generate_command("send receive", board_name, {"timestamp":0, **board.desired_state})
            startup_tasks.append(RecurringTask(command_processor, f"{board_name}_MainTask", board_config['active_interval'], startup_command))
        return startup_tasks
    
    def disarm_all(self):
        for board in self.boards:
            if board.is_actuator:
                # Update the desired state to disarm everything
                if "servos" in board.desired_state:
                    for servo, _ in board.desired_state["servos"].items():
                        board.desired_state["servos"][servo]["armed"] = False
                
                if "solenoids" in board.desired_state:
                    for solenoid, _ in board.desired_state["solenoids"].items():
                        board.desired_state["solenoids"][solenoid]["armed"] = False
                
                if "pyros" in board.desired_state:
                    for pyro, _ in board.desired_state["pyros"].items():
                        board.desired_state["pyros"][pyro]["armed"] = False
        
        return "All actuators disarmed"
    
    def update_board_desired_state(self, board_name, new_desired_state):
        """Update a board's desired state"""
        """This will only change components that are armed"""
        board = self.get_board(board_name)
        if not board:
            print(f"Board {board_name} not found")
            return False
        
        for hw_type, _ in new_desired_state.items():
            if hw_type not in self.hardware_types:
                print(f"Hardware type \'{hw_type}\' not recognized")
                return f"Hardware type \'{hw_type}\' not recognized"

        for hw_type in self.hardware_types:
            if hw_type in new_desired_state and hw_type in board.desired_state:
                for item_name, item_data in new_desired_state[hw_type].items():
                    if item_name in board.state[hw_type]:
                        if "armed" in board.state[hw_type][item_name].keys():
                            if board.state[hw_type][item_name]["armed"]:
                                # Only update the desired state if the item is armed
                                if item_name in board.desired_state[hw_type]:
                                    for key, value in item_data.items():
                                        board.desired_state[hw_type][item_name][key] = value
                                # If not armed, make sure the desired powered must be off
                            else:
                                if "powered" in board.desired_state[hw_type][item_name].keys():
                                    board.desired_state[hw_type][item_name]["powered"] = False
                        if "armed" in new_desired_state[hw_type][item_name].keys():
                            board.desired_state[hw_type][item_name]["armed"] = new_desired_state[hw_type][item_name]["armed"]

        return "Desired state updated successfully"
    def unload_hardware(self):
        # Close all serial connections
        for board in self.boards:
            if board.serialmanager:
                board.serialmanager.close()
                print(f"Closed serial connection for board: {board.name}")
        self.boards = []


    def get_config(self):
        """Return the hardware configuration"""
        return self.config
    
    def set_config(self, data):
        """Set the hardware configuration without reloading board connections"""
        try:
            self.config = json.loads(data)
            with open('hardware_config.json', 'w') as file:
                json.dump(self.config, file, indent=4)
            return "Hardware configuration updated successfully"
        except json.JSONDecodeError:
            return "Invalid JSON format"
        
    async def reload_config(self):
        """Reload the hardware configuration from a file"""
        self.unload_hardware()  # Unload current hardware configuration
        await self.load_hardware()
        return "Hardware configuration reloaded successfully"
        
    async def send_receive(self, board_name, message):
        """Send a message to a specific board and receive the response"""
        board = self.get_board(board_name)
        if not board:
            print(f"Board {board_name} not found")
            return f"Board {board_name} not found"
        if not board.serialmanager:
            print(f"Board {board_name} does not have a serial manager")
            return f"Board {board_name} does not have a serial manager"
        manager = board.serialmanager
        response = await manager.send_receive(message)
        try:
            response_dict = json.loads(response)
            self.update_board_state(board_name, response_dict)
            return response
        except json.JSONDecodeError:
            return response
