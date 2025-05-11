from typing import Optional
from propbackend.utils import backend_logger
import json

class _ConfigReaderSingleton:
    _instance: Optional['_ConfigReaderSingleton'] = None
    _config_json: dict = {}
    _board_config: dict = {}
    _state_defaults: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(_ConfigReaderSingleton, cls).__new__(cls)
            cls._instance._initialize_config()
        return cls._instance
    
    def _initialize_config(self) -> None:
        with open('hardware_config.json', 'r') as file:
            _config_json = json.load(file)
        with open('hardware_config.json', 'w') as file:
            json.dump(_config_json, file, indent=4)

        board_config = _config_json.get("boards", {})
        if not board_config:
            backend_logger.error("Board configuration is empty. Please check the hardware_config.json file.")
            return
        else:
            self._board_config = board_config

        state_defaults = _config_json.get("state_defaults", {})
        if not state_defaults:
            backend_logger.error("State defaults configuration is empty. Please check the hardware_config.json file.")
            return
        else:
            self._state_defaults = state_defaults

    def get_board_config(self) -> dict:
        if not self._board_config:
            backend_logger.error("Board configuration is empty. Please check the hardware_config.json file.")
            return {}
        return self._board_config
    
    def get_state_defaults(self) -> dict:
        if not self._state_defaults:
            backend_logger.error("State defaults configuration is empty. Please check the hardware_config.json file.")
            return {}
        return self._state_defaults
    
    def get_hardware_types(self) -> list:
        if not self._state_defaults:
            backend_logger.error("State defaults configuration is empty. Please check the hardware_config.json file.")
            return []
        return list(self._state_defaults.keys())


config_reader = _ConfigReaderSingleton()