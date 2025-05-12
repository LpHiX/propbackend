from typing import TYPE_CHECKING
from propbackend.utils.time_keeper import TimeKeeper
from propbackend.utils import backend_logger
from propbackend.utils import config_reader
import asyncio


if TYPE_CHECKING:
    from propbackend.hardware.serial_manager import SerialManager
    from propbackend.hardware.board import Board

class SerialCommandScheduler:
    def __init__(self, serial_manager: "SerialManager", board: "Board"):
        self.serial_manager = serial_manager
        self.board = board
        self.update_interval = board.board_config["polling_interval"]
        self.running = True
        self.timekeeper = TimeKeeper(name=f'{self.board.name}_SerialCommandScheduler', cycle_time=self.update_interval)

        self.command = self.create_command()
        asyncio.create_task(self.start_sending())

    def create_command(self):
        if not self.board.is_actuator:
            message = {"timestamp": 0}
            for hw_type in config_reader.get_hardware_types():
                if hw_type in self.board.state:
                    message[hw_type] = {}
                    for item_name, item_data in self.board.state[hw_type].items():
                        message[hw_type][item_name] = {"channel": item_data['channel']}
                        if "value" in item_data:
                            message[hw_type][item_name]["value"] = item_data["value"]                            
            return message
        else:
            return {"timestamp":0, **self.board.desired_state}

    async def start_sending(self):
        while self.running:
            self.timekeeper.cycle_start()
            asyncio.create_task(self.serial_manager.send_receive(self.command))
            await self.timekeeper.cycle_end()
    
    def stop(self):
        self.running = False
        backend_logger.debug(f"SERIALCOMMANDSCHEDULER Serial command scheduler for board {self.board.name} stopped")
