from enum import Enum
import json
import time
import signal
import sys
import serial
import asyncio
import serial_asyncio
import os
import platform
import csv
from datetime import datetime
import copy


class MachineStates(Enum):
    STARTTUP = 0
    IDLE = 1
    ENGINEABORT = 2
    FTS = 3
    HOTFIRE = 4
    LAUNCH = 5
    HOVER = 6


class StateMachine:
    def __init__(self):
        self.state = MachineStates.STARTTUP
        self.hotfirecontroller = self.HotfireController()
        self.changing_state = False
        self.time_keeper = None


    def set_state(self, state):
        self.changing_state = True
        if isinstance(state, MachineStates):
            self.state = state
        else:
            raise ValueError("Invalid state")

    def get_state(self):
        return self.state

    def __str__(self):
        return f"Current State: {self.state.name}"

    def set_time_keeper(self, time_keeper):
        self.time_keeper = time_keeper
    
    class HotfireController():
        def __init__(self):
            with open('hotfiresequence.json', 'r') as file:
                sequencejson = json.load(file)

            self.set_hotfire_sequence(sequencejson)
            
            with open('hotfiresequence.json', 'w') as file:
                    json.dump(self.sequencejson, file, indent=4)

        def set_hotfire_sequence(self, sequencejson):
            self.sequencejson = sequencejson
            with open('hotfiresequence.json', 'w') as file:
                json.dump(self.sequencejson, file, indent=4)
            
            self.time_before_ignition = self.sequencejson["time_before_ignition"]
            self.hotfire_safing_time = self.sequencejson["hotfire_safing_time"]
            self.start_end_desiredstate = self.sequencejson["start_end_desiredstate"]
            sequence = self.sequencejson["sequence"]
            times = []
            timestrs = []
            for timestr, _ in sequence.items():
                time = float(timestr)
                times.append(time)
                timestrs.append(timestr)
            
            self.sorted_times, self.sorted_timestr = (list(t) for t in zip(*sorted(zip(times, timestrs))))

            self.hotfire_end_time = self.sorted_times[-1] + self.hotfire_safing_time

        def is_hotfire_complete(self, time_since_statechange):
            T = self.get_T(time_since_statechange)
            #print(f"Hotfire complete check: T = {T}, hotfire_end_time = {self.hotfire_end_time}")
            if T > self.hotfire_end_time:
                return True
            else:
                return False

        def get_T(self, time_since_statechange):
            T = time_since_statechange - self.time_before_ignition
            return T


        def get_hotfire_sequence(self):
            return self.sequencejson
        
        def get_hotfire_desiredstate(self, time_since_statechange):
            T = self.get_T(time_since_statechange)
            if T < self.sorted_times[0] or T > self.sorted_times[-1]:
                desired_state = self.start_end_desiredstate
            else:
                time_index = 0
                while T > self.sorted_times[time_index]:
                    time_index += 1
                desired_state = self.sequencejson["sequence"][self.sorted_timestr[time_index]]
            
            return desired_state #THIS A DICT OF BOARDS, WITH THEIR DESIRED STATES INSIDE
        
        def get_abort_desiredstate(self):
            return self.start_end_desiredstate


    def start_hotfire(self):
        if self.state != MachineStates.IDLE:
            return f"Cannot start hotfire from current state: {str(self.state)}"
        self.set_state(MachineStates.HOTFIRE)
        print("Hotfire sequence started")
        return "Hotfire sequence started"

    def abort_engine(self):
        self.set_state(MachineStates.ENGINEABORT)
        print("Engine abort sequence started")
        return "Engine abort sequence started"

class TimeKeeper:
    def __init__(self, name, cycle_time, debug_time=0.0):
        self.name = name
        self.debug_time = debug_time
        self.cycle_time = cycle_time
        self.start_time = time.perf_counter()
        self.statechange_time = self.start_time
        self.cycle = 0

    def set_interval(self, cycle_time):
        self.cycle_time = cycle_time
        self.cycle = 0
        self.statechange_time = time.perf_counter()

    def cycle_start(self):
        self.cycle_starttime = time.perf_counter()
        if self.debug_time > 0:
            if(self.cycle % (self.debug_time / self.cycle_time) == 0):
                print(f"TimeKeeper {self.name} is at cycle {self.cycle} at {time.perf_counter() - self.start_time:.5f} seconds")

    def time_since_start(self) -> float:
        return time.perf_counter() - self.start_time
    
    def statechange(self) -> None:
        self.cycle = 0
        self.statechange_time = time.perf_counter()

    def time_since_statechange(self) -> float:
        return time.perf_counter() - self.statechange_time

    async def cycle_end(self):
        self.cycle += 1
        next_time = self.statechange_time + (self.cycle + 1) * self.cycle_time
        await asyncio.sleep(max(0, next_time - time.perf_counter()))  # Sleep for the remaining cycle time


    def get_cycle(self):
        return self.cycle

class SerialManager:
    def __init__(self, board_name, port, baudrate, print_send=False, print_receive=False, emulator=False):
        self.board_name = board_name
        self.emulator = emulator
        self.port = port
        self.baudrate = baudrate
        self.print_send = print_send
        self.print_receive = print_receive
        self.running = False

        self.read_buffer = {}
        self.buffer_lock = asyncio.Lock()
        self.send_id = 0
        self.send_id_lock = asyncio.Lock()

        self.cleanup_queue = []  # Will store (timestamp, id) tuples
        self.cleanup_lock = asyncio.Lock()

        self.reader = None
        self.writer = None

    async def initialize(self):
        """Initialize the serial connection"""
        if self.emulator:
            print("SERIALMANAGER Emulator mode - no serial connection")
            return None
        
        return await self._initialize_serial()

    async def _initialize_serial(self):
        try:
            self.reader, self.writer = await serial_asyncio.open_serial_connection(
                url=self.port,
                baudrate=self.baudrate
            )
            print(f"SERIALMANAGER Serial port {self.port} opened at {self.baudrate} baud for board {self.board_name}")
            
            # Start the background reading thread
            self.running = True

            self.read_task = asyncio.create_task(self._read_loop())
            self.cleanup_task = asyncio.create_task(self._readbuffer_cleanloop())

            return True
            
        except serial.SerialException as e:
            print(f"SERIALMANAGER Error opening port {self.port}: {e}")
            self.reader = None
            self.writer = None
            return False

    async def _read_loop(self):
        """Background thread that continuously reads from serial port"""
        while self.running:
            try:
                line = await self.reader.readline()
                if not line:
                    continue

                data = line.decode('utf-8').strip()
                if not data:
                    continue

                if self.print_receive:
                    print(f"SERIALMANAGER Received: {data}")

                try:
                    message_json = json.loads(data)
                    #print(f"SERIALMANAGER JSON: {json.dumps(message_json, indent=4)}")
                    if "send_id" in message_json:
                        send_id = message_json["send_id"]
                        async with self.buffer_lock:
                            self.read_buffer[send_id] = message_json

                        cleanup_time = time.perf_counter() + 1.0  # 1 second timeout
                        async with self.cleanup_lock:
                            self.cleanup_queue.append((cleanup_time, send_id))
                except json.JSONDecodeError:
                    print(f"SERIALMANAGER JSON Decode error: {data}")
            except Exception as e:
                print(f"SERIALMANAGER Read error: {e}")
                await asyncio.sleep(0.1)  # Longer sleep on error

    async def _readbuffer_cleanloop(self):
        while self.running:
            try:
                next_cleanup_time = None
                cleanup_id = None
                
                async with self.cleanup_lock:
                    if self.cleanup_queue:
                        self.cleanup_queue.sort()
                        now = time.perf_counter()   

                        while self.cleanup_queue and self.cleanup_queue[0][0] < now:
                            _, cleanup_id = self.cleanup_queue.pop(0)
                            async with self.buffer_lock:
                                if cleanup_id in self.read_buffer:
                                    print("SERIALMANAGER Cleanup: Removing message with send_id", cleanup_id)
                                    del self.read_buffer[cleanup_id]
                        
                        if self.cleanup_queue:
                            next_cleanup_time = self.cleanup_queue[0][0]
                if next_cleanup_time is not None:
                    await asyncio.sleep(max(0.1, next_cleanup_time - time.perf_counter()))
                else:
                    await asyncio.sleep(0.1)
            except Exception as e:
                print(f"SERIALMANAGER Cleanup error: {e}")
                await asyncio.sleep(0.1)

    async def send_receive(self, message_json:dict) -> str:
        """Send message to serial port (non-blocking)"""
        if not self.writer:
            #print("SERIALMANAGER Error: Serial port not open")
            return "SERIALMANAGER Error: Serial port not open"
        try:
            async with self.send_id_lock:
                send_id = self.send_id
                self.send_id += 1
            message_json["send_id"] = send_id
            message = json.dumps(message_json)

            self.writer.write(message.encode())
            await self.writer.drain()

            if self.print_send:
                print(f"SERIALMANAGER Sent: {message.strip()}")

            start_time = time.perf_counter()
            timeout_time = 1.0  # 1 second timeout
            while True:
                async with self.buffer_lock:
                    if send_id in self.read_buffer:
                        response = json.dumps(self.read_buffer[send_id])
                        del self.read_buffer[send_id]
                        return response
                if time.perf_counter() - start_time > timeout_time:
                    print(f"SERIALMANAGER Timeout waiting for response with send_id {send_id} for board {self.board_name}")
                    return f"SERIALMANAGER Timeout waiting for response with send_id {send_id} for board {self.board_name}"
                await asyncio.sleep(0.001)
        except Exception as e:
            print(f"SERIALMANAGER Send error: {e}")
            return f"SERIALMANAGER Send error: {e}"

    def is_connected(self):
        """Check if serial connection is active"""
        return self.reader is not None and self.writer is not None
        
    def close(self):
        """Close the serial connection gracefully"""
        self.running = False

        if hasattr(self, 'read_task'):
            self.read_task.cancel()
        if hasattr(self, 'cleanup_task'):
            self.cleanup_task.cancel()

        if self.writer:
            self.writer.close()
            print(f"SERIALMANAGER Serial port {self.port} closed")

class Board:
    def __init__(self, name: str, serialmanager: SerialManager, state: dict, config: dict, desired_state: dict=None):
        self.name: str = name
        self.serialmanager: SerialManager = serialmanager
        self.state: dict = state
        self.config: dict = config
        self.desired_state: dict = desired_state if desired_state is not None else {}
        self.is_actuator: bool = config.get('is_actuator', False)

        #print(f"Board {self.name}'s state: {json.dumps(self.state, indent=4)}")
        #print(f"Board {self.name}'s desired_state: {json.dumps(self.desired_state, indent=4)}")

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

class BoardStateLogger:
    def __init__(self, name, hardware_handler: HardwareHandler, log_dir="/mnt/proppi_data/logs"):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

        self.current_csv = None
        self.csv_writer = None
        self.name = name
    
        self.file_name = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.name}.csv"
        self.csv_path = f"{self.log_dir}/{self.file_name}"
        self.current_csv = open(self.csv_path, 'w', newline='')
        self.csv_writer = csv.writer(self.current_csv)
        self.current_csv.write(f"#Test started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        self.start_time = time.perf_counter()

        self.state_defaults = hardware_handler.state_defaults
    
    def write_headers(self, boards: list[Board]):
        headers = ["timestamp"]
        for board in boards:
            #print(json.dumps(board.state, indent=4))
            for hw_type, items in board.state.items():
                if not isinstance(items, dict):
                    continue
                for item_name, _ in items.items():
                    for state_name in self.state_defaults[hw_type].keys():
                        headers.append(f"{board.name}_{hw_type}_{item_name}_{state_name}")
            for hw_type, items in board.desired_state.items():
                if not isinstance(items, dict):
                    continue
                for item_name, _ in items.items():
                    for state_name in self.state_defaults[hw_type].keys():
                        headers.append(f"{board.name}_{hw_type}_{item_name}_{state_name}_desiredstate")
        
        self.csv_writer.writerow(headers)

    def write_data(self, boards: list[Board]):
        data = [time.perf_counter() - self.start_time]
        for board in boards:
            for hw_type, items in board.state.items():
                if not isinstance(items, dict):
                    continue
                for item_name, item_data in items.items():
                    if hw_type in self.state_defaults:
                        for state_name in self.state_defaults[hw_type].keys():
                            #print(f"{board.name}_{hw_type}_{item_name}_{state_name}")
                            data.append(item_data[state_name])
            for hw_type, items in board.desired_state.items():
                if not isinstance(items, dict):
                    continue
                if hw_type in self.state_defaults:
                    for item_name, item_data in items.items():
                        #print(f"{board.name}_{hw_type}_{item_name} has item data {item_data}")
                        for state_name in self.state_defaults[hw_type].keys():
                            #print(f"{board.name}_{hw_type}_{item_name}_{state_name}")
                            if state_name in item_data:
                                data.append(item_data[state_name])
                            else:
                                data.append(None)

        self.csv_writer.writerow(data)
        self.current_csv.flush()

    def close(self):
        if self.current_csv:
            self.current_csv.close()
            print(f"BoardStateLogger: Closed CSV file {self.file_name}")
        self.current_csv = None
        self.csv_writer = None

class CommandProcessor:
    def __init__(self, state_machine: StateMachine, hardware_handler: HardwareHandler):
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
        

class RecurringTask:
    def __init__(self, command_processor: CommandProcessor, name: str, interval: float, command: dict):
        self.command_processor = command_processor
        self.name = name
        self.interval = interval
        self.command = command
        self.timekeeper = TimeKeeper(self.name, cycle_time=interval)
        self.running = True
    async def start_task(self):
        print(f"Starting task: {self.name} with interval {self.interval}")
        #print(json.dumps(self.command, indent=4))
        while self.running:
            self.timekeeper.cycle_start()
            # if(self.command["data"]["board_name"] == "ActuatorBoard"):
            #     print(f"Sending command to actuator board: {json.dumps(self.command)}")
            asyncio.create_task(self.command_processor.process_message(json.dumps(self.command)))
            await self.timekeeper.cycle_end()
    def set_interval(self, interval: float):
        self.interval = interval
        self.timekeeper.set_interval(interval)
        print(f"Task {self.name} interval set to {self.interval}")
    def kill_task(self):
        self.running = False
        print(f"Stopping task: {self.name}")

class RecurringTaskHandler:
    def __init__(self, state_machine: StateMachine, command_processor: CommandProcessor, hardware_handler: HardwareHandler):
        self.hardware_handler = hardware_handler
        self.state_machine = state_machine
        self.command_processor = command_processor
        self.recurring_tasks: list[RecurringTask] = []

        if state_machine.get_state() == MachineStates.STARTTUP:
            self.on_machine_startup()

    def on_machine_startup(self):
        for recurring_task in self.recurring_tasks:
            recurring_task.kill_task()

        self.recurring_tasks = self.command_processor.get_startup_tasks(self.command_processor)
        for recurring_task in self.recurring_tasks:
            asyncio.create_task(recurring_task.start_task())

        if self.state_machine.get_state() == MachineStates.IDLE:
            self.set_tasks_idle()

    def set_tasks_idle(self):
        for board in self.hardware_handler.boards:
            idle_interval = board.config["idle_interval"]
            recurring_task = self.get_recurring_task(f'{board.name}_MainTask')
            if recurring_task:
                recurring_task.set_interval(idle_interval)

    def set_tasks_active(self):
        for board in self.hardware_handler.boards:
            active_interval = board.config["active_interval"]
            recurring_task = self.get_recurring_task(f'{board.name}_MainTask')
            if recurring_task:
                recurring_task.set_interval(active_interval)

    def stop_task(self, task):
        task.kill_task()

    def get_recurring_task(self, recurring_task_name) -> RecurringTask:
        for recurring_task in self.recurring_tasks:
            if recurring_task.name == recurring_task_name:
                return recurring_task
        return None

    def get_tasks(self) -> list[RecurringTask]:
        return self.recurring_tasks

class UDPServer:
    def __init__(self, command_processor: CommandProcessor, host='0.0.0.0', port=8888, print_send=False, print_receive=False):
        self.command_processor = command_processor
        self.host = host
        self.port = port
        self.print_send = print_send
        self.print_receive = print_receive

        self.transport = None
        self.protocol = None

        asyncio.create_task(self._start_server())

        print(f"UDP server listening on {self.host}:{self.port}")

    async def _start_server(self):
        """Start the UDP server using asyncio"""
        class UDPServerProtocol(asyncio.DatagramProtocol):
            def __init__(self, server: UDPServer):
                self.server = server
                
            def connection_made(self, transport):
                self.server.transport = transport
                
            def datagram_received(self, data, addr):
                message = data.decode('utf-8').strip()
                if self.server.print_receive:
                    print(f"UDP Received: '{message}' from {addr}")
                
                # Process the message
                asyncio.create_task(self._process_message(message, addr))

            async def _process_message(self, message, addr):
                try:
                    response = await self.server.command_processor.process_message(message) 
                    self.server.transport.sendto(response.encode('utf-8'), addr)
                except Exception as e:
                    print(f"Error processing message: {e}")
                    error_response = f"Error processing message: {e}"
                    self.server.transport.sendto(error_response.encode('utf-8'), addr)
        
        loop = asyncio.get_running_loop()
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: UDPServerProtocol(self),
            local_addr=(self.host, self.port)
        )
    
    def stop(self):
        """Stop the server"""
        if self.transport:
            self.transport.close()
        print("UDP Server stopped")

class SignalHandler:
    def __init__(self, udp_server, windows=False):
        self.udp_server = udp_server
        signal.signal(signal.SIGINT, self.handle_signal)  # Handle Ctrl+C
        signal.signal(signal.SIGTERM, self.handle_signal)  # Handle termination
        if(not windows):
            signal.signal(signal.SIGTSTP, self.handle_suspend)

    def handle_signal(self, signum, frame):
        print(f"Received signal {signum}, stopping server...")
        self.udp_server.stop()
        sys.exit(0)

    def handle_suspend(self, signum, frame):
        """Handle process suspension (Ctrl+Z)"""
        print("\nProcess being suspended, cleaning up resources...")
        self.udp_server.stop()
        # Re-raise SIGTSTP to actually suspend after cleanup
        signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTSTP)



async def main(windows=False, emulator=False):
    deployment_power = False

    state_machine = StateMachine()

    hardware_handler = HardwareHandler(emulator=emulator, debug_prints=False)
    await hardware_handler.initialize()

    command_processor = CommandProcessor(state_machine, hardware_handler)
    udp_server = UDPServer(command_processor, print_send=False, print_receive=False)
    signal_handler = SignalHandler(udp_server, windows) #To handle system interrupts
    
    print("Startup Complete, waiting for commands")
    recurring_taskhandler = RecurringTaskHandler(state_machine, command_processor, hardware_handler)
    command_processor.set_recurring_task_handler(recurring_taskhandler)


    main_loop_time_keeper = TimeKeeper(name="MainLoop", cycle_time=0.01, debug_time=60.0)
    state_machine.set_time_keeper(main_loop_time_keeper)
    
    #main_loop_logger = BoardStateLogger("MainLoop", hardware_handler)
    #main_loop_logger.write_headers(hardware_handler.boards)


    try:
        while True:
            main_loop_time_keeper.cycle_start()

            current_state = state_machine.get_state()

            if state_machine.changing_state:
                main_loop_time_keeper.statechange()     
                state_machine.changing_state = False


            # Perform actions based on current state
            if current_state == MachineStates.STARTTUP:
                if main_loop_time_keeper.time_since_statechange() > 5:
                    state_machine.set_state(MachineStates.IDLE)
                    command_processor.disarm_all(None)
                    print("State changed to IDLE")
            
            elif current_state == MachineStates.IDLE:
                if main_loop_time_keeper.cycle == 0:
                    recurring_taskhandler.set_tasks_idle()
                pass
                    

            elif current_state == MachineStates.ENGINEABORT:
                if main_loop_time_keeper.cycle == 0:
                    recurring_taskhandler.set_tasks_active()

                abort_desiredstates = state_machine.hotfirecontroller.get_abort_desiredstate()
                for board_name, desired_state in abort_desiredstates.items():
                    hardware_handler.update_board_desired_state(board_name, desired_state)

            elif current_state == MachineStates.FTS:
                pass

            elif current_state == MachineStates.HOTFIRE:
                if main_loop_time_keeper.cycle == 0:
                    recurring_taskhandler.set_tasks_active()
                    #hotfire_logger = BoardStateLogger("HotfireLog", hardware_handler)
                    #hotfire_logger.write_headers(hardware_handler.boards)

                
                time_since_statechange = main_loop_time_keeper.time_since_statechange()

                T = state_machine.hotfirecontroller.get_T(time_since_statechange)
                if (main_loop_time_keeper.get_cycle() % 100 == 0):
                    print(f"T{T:.2f}s")
                board_desiredstates = state_machine.hotfirecontroller.get_hotfire_desiredstate(time_since_statechange)
                for board_name, desired_state in board_desiredstates.items():
                    hardware_handler.update_board_desired_state(board_name, desired_state)
                
                #hotfire_logger.write_data(hardware_handler.boards)

                if state_machine.hotfirecontroller.is_hotfire_complete(time_since_statechange):
                    print(f"HOTFIRE COMPLETE at T{T:.2f}s")
                    #hotfire_logger.close()
                    state_machine.set_state(MachineStates.IDLE)
                    main_loop_time_keeper.statechange()
                    command_processor.disarm_all(None)
                    print("State changed to IDLE")
                
            elif current_state == MachineStates.LAUNCH:
                pass

            elif current_state == MachineStates.HOVER:
                states = {}
                for board in hardware_handler.boards:
                    states[board.name] = board.state
                
                #---------------------------------------
                desired_states = {}
                #Implement control system here!!!!!!!!!
                #desired_states = controlsystem(states)
                #---------------------------------------

                hardware_handler = hardware_handler.update_board_desired_state("ActuatorBoard", desired_states)
            
            # Sleep to avoid excessive CPU usage
            #if main_loop_time_keeper.cycle % 10 == 0:
                #main_loop_logger.write_data(hardware_handler.boards)
            await main_loop_time_keeper.cycle_end()

    except KeyboardInterrupt:
        signal_handler.handle_signal(signal.SIGINT, None)

if __name__ == "__main__":
    print("=====================Starting backend...======================")
    if platform.system() != "Windows":
        try:
            import uvloop
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            print("Using uvloop for enhanced performance")
        except ImportError:
            print("uvloop not available. Run: pip install uvloop for better performance")
        asyncio.run(main())
    else:
        print("Running on Windows - standard event loop will be used")
        asyncio.run(main(windows=True))
    #syncio.run(main(emulator=True))

    '''
    TODO
    - Logging of each state to a csv file (Ability to name it after a test)
    - hotfires  
    - UDP and serial json logging
    Lower priority
    - have board name be the key for each board instead of a property in board list
    - turn lists into dicts
    - Only send json through if it exists in the hardware configuration, unless unsafe=true


    - hardware json to gui

    '''