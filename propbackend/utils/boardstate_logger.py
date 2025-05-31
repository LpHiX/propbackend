from propbackend.hardware.hardware_handler import HardwareHandler
from propbackend.hardware.board import Board
import os
from datetime import datetime
import csv
import time

from propbackend.utils import config_reader

class BoardStateLogger:
    def __init__(self, name, hardware_handler: HardwareHandler, log_dir="/mnt/proppi_data/logs"):
        self.name = name
        self.log_dir = log_dir
        self.hardware_handler = hardware_handler

        os.makedirs(log_dir, exist_ok=True)

        self.file_name = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self.name}.csv"
        self.csv_path = f"{self.log_dir}/{self.file_name}"

        self.current_csv = open(self.csv_path, 'w', newline='')
        self.csv_writer = csv.writer(self.current_csv)
    
        comment_test = f"#Test started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        for board in self.hardware_handler.boards:
            for hw_type in config_reader.get_hardware_types():
                if hw_type in board.board_config:
                    for item_name, item_data in board.board_config[hw_type].items():
                        if item_data.get("adc"):
                            comment_test += f"ADC_{hw_type}_{item_name}_gain:{item_data['gain']}_offset:{item_data['offset']} "

        comment_test += "\n"
        self.current_csv.write(comment_test)
        self.start_time = time.perf_counter()

        self.state_defaults = config_reader.get_state_defaults()
    
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

        if self.current_csv:
            self.csv_writer.writerow(data)
            self.current_csv.flush()

    def close(self):
        if self.current_csv:
            self.current_csv.close()
            print(f"BoardStateLogger: Closed CSV file {self.file_name}")
        self.current_csv = None
        self.csv_writer = None

