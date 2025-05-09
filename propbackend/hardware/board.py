from .serial_manager import SerialManager

class Board:
    def __init__(self, name: str, serialmanager: SerialManager, state: dict, config: dict, desired_state: dict=None):
        self.name: str = name
        self.serialmanager: SerialManager = serialmanager
        self.state: dict = state
        self.config: dict = config
        self.desired_state: dict = desired_state if desired_state is not None else {}
        self.is_actuator: bool = config.get('is_actuator', False)

