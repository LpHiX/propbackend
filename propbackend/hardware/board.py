from propbackend.utils import backend_logger
from propbackend.utils import config_reader
from propbackend.hardware.serial_manager import SerialManager
from propbackend.hardware.serial_command_scheduler import SerialCommandScheduler
from propbackend.hardware.udp_manager import UDPManager
from propbackend.hardware.udp_command_scheduler import UDPCommandScheduler
import asyncio
import copy
import json

from typing import cast

class Board:
    def __init__(self, name: str, board_config: dict):
        self.name: str = name
        self.board_config: dict = board_config

        self.state: dict = {}
        self.desired_state: dict = {}


        if 'serial' in board_config:
            self.serialmanager: SerialManager = cast(SerialManager, None)
            self.serialscheduler: SerialCommandScheduler = cast(SerialCommandScheduler, None)
            asyncio.create_task(self.initialise_serial())

        if 'udp' in board_config:
            self.udpmanager: UDPManager = cast(UDPManager, None)
            self.udpscheduler: UDPCommandScheduler = cast(UDPCommandScheduler, None)
            asyncio.create_task(self.initialise_udp())

        for hw_type in config_reader.get_hardware_types():
            if hw_type in board_config:
                self.state[hw_type] = {}
                for item_name, item_data in board_config[hw_type].items():
                    self.state[hw_type][item_name] = {**config_reader.get_state_defaults()[hw_type].copy(), **item_data}
        
        self.is_actuator: bool = board_config.get('is_actuator', False)
        if self.is_actuator:
            self.desired_state = copy.deepcopy(self.state) # WHAT THE FUCK, NESTED DICTIONARIES WERE STILL REFERENCE BASED, LEADING TO UPDATING DESIRED STATES UPDATING ACTUAL STATES
            if "servos" in board_config:
                self.desired_state["servos"] = {}
                for servo_name, servo_data in board_config["servos"].items():
                    self.desired_state["servos"][servo_name] = {"channel": servo_data['channel'], "armed": False}
                    if 'safe_angle' in servo_data:
                        self.desired_state["servos"][servo_name]["armed"] = True
                        self.desired_state["servos"][servo_name]["angle"] = servo_data['safe_angle']
        

    async def initialise_serial(self) -> bool:
        serial_config = self.board_config.get('serial', {})
        if 'port' in serial_config and 'baudrate' in serial_config:
            try:
                serial_manager = SerialManager(
                    board=self,
                    port=serial_config['port'],
                    baudrate=serial_config['baudrate'],
                )
                await serial_manager.initialize()
                self.serialmanager = serial_manager
            except Exception as e:
                backend_logger.error(f"Failed to initialize serial for board {self.name}: {e}")
                return False
        else:
            backend_logger.error(f"Board {self.name} is missing port or baudrate configuration")
            return False
        
        if self.serialmanager:
            self.serialscheduler = SerialCommandScheduler(
                serial_manager=self.serialmanager,
                board=self
            )
        return True
    
    async def initialise_udp(self) -> bool:
        udp_config = self.board_config.get('udp', {})
        if 'ip' in udp_config and 'port' in udp_config:
            try:
                udp_manager = UDPManager(
                    board=self,
                    ip=udp_config['ip'],
                    port=udp_config['port'],
                )
                await udp_manager.initialize()
                self.udpmanager = udp_manager
            except Exception as e:
                backend_logger.error(f"Failed to initialize UDP for board {self.name}: {e}")
                return False
        else:
            backend_logger.error(f"Board {self.name} is missing IP or port configuration")
            return False
        
        if self.udpmanager:
            self.udpscheduler = UDPCommandScheduler(
                udp_manager=self.udpmanager,
                board=self
            )
        return True


    def update_state(self, new_state: dict) -> None:
        for hw_type in config_reader.get_hardware_types():
            if hw_type in new_state and hw_type in self.state:  #Only update state if defined in config
                if new_state[hw_type] is not None:
                    for item_name, item_data in new_state[hw_type].items():
                        if item_name in self.state[hw_type]:
                            for key, value in item_data.items():
                                self.state[hw_type][item_name][key] = value

    def update_desired_state(self, new_desired_state: dict) -> None:
        for hw_type in config_reader.get_hardware_types():
            if hw_type in new_desired_state and hw_type in self.desired_state:
                for item_name, item_data in new_desired_state[hw_type].items():
                    if item_name in self.state[hw_type]:
                        if "armed" in self.state[hw_type][item_name].keys():
                            if self.state[hw_type][item_name]["armed"]:
                                # Only update the desired state if the item is armed
                                if item_name in self.desired_state[hw_type]:
                                    for key, value in item_data.items():
                                        self.desired_state[hw_type][item_name][key] = value
                                # If not armed, make sure the desired powered must be off
                            else:
                                if "powered" in self.desired_state[hw_type][item_name].keys():
                                    self.desired_state[hw_type][item_name]["powered"] = False
                        if "armed" in new_desired_state[hw_type][item_name].keys():
                            self.desired_state[hw_type][item_name]["armed"] = new_desired_state[hw_type][item_name]["armed"]
                            if hw_type == "servos":
                                if new_desired_state[hw_type][item_name]["armed"] == False:
                                    if "disarm_angle" in self.board_config["servos"][item_name].keys():
                                        self.desired_state["servos"][item_name]["angle"] = 0
    
    def disarm_all(self) -> None:
        if self.is_actuator:
            if "servos" in self.desired_state:
                for servo, _ in self.desired_state["servos"].items():
                    self.desired_state["servos"][servo]["armed"] = False
            
            if "solenoids" in self.desired_state:
                for solenoid, _ in self.desired_state["solenoids"].items():
                    self.desired_state["solenoids"][solenoid]["armed"] = False
            
            if "pyros" in self.desired_state:
                for pyro, _ in self.desired_state["pyros"].items():
                    self.desired_state["pyros"][pyro]["armed"] = False
    
    def shutdown(self) -> None:
        if hasattr(self, 'serialmanager') and self.serialmanager:
            self.serialscheduler.stop()
            self.serialmanager.close()
            backend_logger.debug(f"BOARD Closed serial connection for board {self.name}")