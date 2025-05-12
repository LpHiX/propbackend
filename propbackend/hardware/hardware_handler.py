import json
from propbackend.hardware.board import Board
from propbackend.hardware.serial_manager import SerialManager
from propbackend.utils.backend_logger import backend_logger
from propbackend.utils import config_reader

import copy

class HardwareHandler:
    def __init__(self):
        self.boards: list[Board] = []

    async def initialize(self):
        """Initialize all hardware asynchronously"""
        return await self.load_hardware()
    
    def get_board(self, board_name):
        """Get a board by name"""
        for board in self.boards:
            if board.name == board_name:
                return board
        return None

    
    async def load_hardware(self):
        for board_name, board_config in config_reader.get_board_config().items():
            self.boards.append(Board(board_name, board_config))
    
    def unload_hardware(self):
        # Close all serial connections
        for board in self.boards:
            board.shutdown()
        self.boards = []
        
    # async def send_receive(self, board_name, message):
    #     """Send a message to a specific board and receive the response"""
    #     board = self.get_board(board_name)
    #     if not board:
    #         print(f"Board {board_name} not found")
    #         return f"Board {board_name} not found"
    #     if not board.serialmanager:
    #         print(f"Board {board_name} does not have a serial manager")
    #         return f"Board {board_name} does not have a serial manager"
    #     manager = board.serialmanager
    #     response = await manager.send_receive(message)
    #     try:
    #         response_dict = json.loads(response)
    #         self.update_board_state(board_name, response_dict)
    #         return response
    #     except json.JSONDecodeError:
    #         return response
