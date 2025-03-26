from enum import Enum
import json
import socket
import threading
import time
import signal
import sys

class MachineStates(Enum):
    STARTUP = 1
    IDLE = 2
    FTS = 3
    HOTFIRE = 4
    LAUNCH = 5
    HOVER = 6

class StateMachine:
    def __init__(self):
        self.state = MachineStates.STARTUP

    def set_state(self, state):
        if isinstance(state, MachineStates):
            self.state = state
        else:
            raise ValueError("Invalid state")

    def get_state(self):
        return self.state

    def __str__(self):
        return f"Current State: {self.state.name}"

class UDPCommandServer:
    def __init__(self, command_handler, host='0.0.0.0', port=8888):
        self.command_handler = command_handler
        self.host = host
        self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = True
        self.socket.bind((self.host, self.port))
        self.server_thread = threading.Thread(target=self._server_loop)
        self.server_thread.daemon = True # Thread will exit with main program exits
        self.server_thread.start()

        print(f"UDP server listening on {self.host}:{self.port}")

    def _server_loop(self):
        """Main server loop running in a separate thread"""
        while self.running:
            try:
                data, addr = self.socket.recvfrom(1024)
                message = data.decode('utf-8').strip()
                print(f"Received: '{message}' from {addr}")
                self.command_handler.process_message(message, self.socket, addr)
            except Exception as e:
                if self.running:
                    print(f"Error: {e}")
    
    def stop(self):
        """Stop the server"""
        self.running = False
        self.socket.close()
        print("Server stopped")

class CommandHandler:
    def __init__(self, hardware_handler):
        self.hardware_handler = hardware_handler
        self.command_handlers = {
            "get hardware json": self.get_hardware_json,
            "set hardware json": self.set_hardware_json,
        }

    def process_message(self, command, socket, addr):
        message_json = json.loads(command)
        command = message_json["command"]
        data = message_json["data"]
        response = f"Unknown command: {command}"
        if command in self.command_handlers:
            response = self.command_handlers[command](data)

        socket.sendto(response.encode('utf-8'), addr)

    def get_hardware_json(self, _):
        return json.dumps(self.hardware_handler.get_config())
    def set_hardware_json(self, data):
        return self.hardware_handler.set_config(data)
        

class HardwareHandler:
    def __init__(self):
        with open('hardware_config.json', 'r') as file:
            self.config = json.load(file)

    def get_config(self):
        """Return the hardware configuration"""
        return self.config
    
    def set_config(self, data):
        """Set the hardware configuration"""
        try:
            self.config = json.loads(data)
            with open('hardware_config.json', 'w') as file:
                json.dump(self.config, file)
            return "Hardware configuration updated successfully"
        except json.JSONDecodeError:
            return "Invalid JSON format"

class SignalHandler:
    def __init__(self, udp_server):
        self.udp_server = udp_server
        signal.signal(signal.SIGINT, self.handle_signal)  # Handle Ctrl+C
        signal.signal(signal.SIGTERM, self.handle_signal)  # Handle termination
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

if __name__ == "__main__":
    state_machine = StateMachine()
    
    hardware_handler = HardwareHandler()

    command_handler = CommandHandler(hardware_handler)
    udp_server = UDPCommandServer(command_handler)

    signal_handler = SignalHandler(udp_server)
    print(state_machine)
    print("Waiting for command")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
        