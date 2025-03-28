from enum import Enum
import json
import socket
import threading
import time
import signal
import sys
import serial
import os
from concurrent.futures import ThreadPoolExecutor

class MachineStates(Enum):
    IDLE = 1
    ABORT = 2
    HOTFIRE = 3
    LAUNCH = 4
    HOVER = 5

class StateMachine:
    def __init__(self):
        self.state = MachineStates.IDLE

    def set_state(self, state):
        if isinstance(state, MachineStates):
            self.state = state
        else:
            raise ValueError("Invalid state")

    def get_state(self):
        return self.state

    def __str__(self):
        return f"Current State: {self.state.name}"

class SerialManager:
    def __init__(self, port, baudrate, print_send=False, print_recieve=False):
        self.port = port
        self.baudrate = baudrate
        self.print_send = print_send
        self.print_recieve = print_recieve
        self.running = False
        self.read_buffer = {}
        self.buffer_lock = threading.Lock()
        self.send_id = 0
        self.send_id_lock = threading.Lock()

        self.cleanup_queue = []  # Will store (timestamp, id) tuples
        self.cleanup_lock = threading.Lock()
        
        # Single cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_scheduler_loop)
        self.cleanup_thread.daemon = True
        self.cleanup_thread.start()

        
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=0.1  # Short timeout to make reads non-blocking
            )
            print(f"SERIALMANAGER Serial port {self.port} opened at {self.baudrate} baud")
            
            # Start the background reading thread
            self.running = True
            self.read_thread = threading.Thread(target=self._read_loop)
            self.read_thread.daemon = True
            self.read_thread.start()

            
            
        except serial.SerialException as e:
            print(f"SERIALMANAGER Error opening port {self.port}: {e}")
            self.serial = None

    def _read_loop(self):
        """Background thread that continuously reads from serial port"""
        while self.running:
            try:
                if self.serial and self.serial.in_waiting > 0:
                    data = self.serial.readline().decode('utf-8').strip()
                    if data:
                        if self.print_recieve:
                            print(f"SERIALMANAGER Received: {data}")
                        try:
                            message_json = json.loads(data)
                            if "send_id" in message_json:
                                with self.buffer_lock:
                                    self.read_buffer[message_json["send_id"]] = message_json
                                cleanup_time = time.time() + 1.0  # 1 second timeout
                                with self.cleanup_lock:
                                    self.cleanup_queue.append((cleanup_time, message_json["send_id"]))
                        except json.JSONDecodeError:
                            print(f"SERIALMANAGER JSON Decode error: {data}")
                time.sleep(0.001)  # Small sleep to prevent CPU hogging
            except Exception as e:
                print(f"SERIALMANAGER Read error: {e}")
                time.sleep(0.1)  # Longer sleep on error

    def _readbuffer_cleanloop(self):
        while self.running:
            try:
                next_cleanup_time = None
                cleanup_id = None
                
                with self.cleanup_lock:
                    if self.cleanup_queue:
                        self.cleanup_queue.sort()
                        now = time.time()   

                        while self.cleanup_queue and self.cleanup_queue[0][0] < now:
                            _, cleanup_id = self.cleanup_queue.pop(0)
                            with self.buffer_lock:
                                if cleanup_id in self.read_buffer:
                                    print("SERIALMANAGER Cleanup: Removing message with send_id", cleanup_id)
                                    del self.read_buffer[cleanup_id]
                        
                        if self.cleanup_queue:
                            next_cleanup_time = self.cleanup_queue[0][0]
                if next_cleanup_time is not None:
                    time.sleep(max(0.1, next_cleanup_time - time.time()))
                else:
                    time.sleep(0.1)
            except Exception as e:
                print(f"SERIALMANAGER Cleanup error: {e}")
                time.sleep(0.1)

    def send_receive(self, message_json, sendresponse_lambda):
        """Send message to serial port (non-blocking)"""
        if not self.serial:
            print("SERIALMANAGER Error: Serial port not open")
            return False
        try:
            with self.send_id_lock:
                send_id = self.send_id
                self.send_id += 1
            message_json["send_id"] = send_id
            message = json.dumps(message_json)
            self.serial.write(message.encode())
            if self.print_send:
                print(f"SERIALMANAGER Sent: {message.strip()}")
            timeout_time = 1
            thread = threading.Thread(target=self._async_receive, args=(send_id, sendresponse_lambda, timeout_time))
            thread.daemon = True  # Daemonize thread to exit with main program
            thread.start()

            return True
        except Exception as e:
            print(f"SERIALMANAGER Send error: {e}")
            return False

    def _async_receive(self, send_id, sendresponse_lambda, timeout_time):
        """Non-blocking receive - returns oldest message or None"""
        start_time = time.time()
        while self.read_buffer.get(send_id) is None:
            if time.time() - start_time > timeout_time:
                print(f"SERIALMANAGER Timeout waiting for response with send_id {send_id}")
                sendresponse_lambda(f"SERIALMANAGER Timeout waiting for response with send_id {send_id}")
                return
            time.sleep(0.01)
        with self.buffer_lock:
            sendresponse_lambda(json.dumps(self.read_buffer[send_id]))
            del self.read_buffer[send_id]
            return
        return None

    def is_connected(self):
        """Check if serial connection is active"""
        return self.serial is not None and self.serial.is_open
        
    def close(self):
        """Close the serial connection gracefully"""
        self.running = False
        time.sleep(0.1)  # Give read thread time to exit
        if self.serial and self.serial.is_open:
            self.serial.close()
            print(f"SERIALMANAGER Serial port {self.port} closed")


class HardwareHandler:
    def __init__(self):
        self.serial_managers = {}

        with open('hardware_config.json', 'r') as file:
            self.config = json.load(file)
        with open('hardware_config.json', 'w') as file:
                json.dump(self.config, file, indent=4)

        
        self.load_hardware()
    
    def load_hardware(self):
        # Initialize serial managers for each board in the configuration
        if 'boards' in self.config:
            for board in self.config['boards']:
                board_name = board['board_name']
                serial_config = board['serial']
                
                if 'port' in serial_config and 'baudrate' in serial_config:
                    try:
                        self.serial_managers[board_name] = SerialManager(
                            port=serial_config['port'],
                            baudrate=serial_config['baudrate']
                        )
                        print(f"Initialized serial connection for board: {board_name}")
                    except Exception as e:
                        print(f"Failed to initialize serial for board {board_name}: {e}")
                else:
                    print(f"Board {board_name} is missing port or baudrate configuration")
        else:
            print("No boards found in configuration or invalid board configuration")

    def unload_hardware(self):
        # Close all serial connections
        for board_name, manager in self.serial_managers.items():
            manager.close()
            print(f"Closed serial connection for board: {board_name}")
        self.serial_managers.clear()

    def get_serial_manager(self, board_name) -> SerialManager:
        """Get the serial manager for a specific board"""
        return self.serial_managers.get(board_name, None)

    def get_config(self):
        """Return the hardware configuration"""
        return self.config
    
    def set_config(self, data):
        """Set the hardware configuration"""
        try:
            self.config = json.loads(data)
            with open('hardware_config.json', 'w') as file:
                json.dump(self.config, file, indent=4)
            return "Hardware configuration updated successfully"
        except json.JSONDecodeError:
            return "Invalid JSON format"
        
    def reload_config(self):
        """Reload the hardware configuration from a file"""
        self.unload_hardware()  # Unload current hardware configuration
        self.load_hardware()
        return "Hardware configuration reloaded successfully"
        
    def send_receive(self, board_name, message, sendresponse_lambda):
        """Send a message to a specific board and receive the response"""
        manager = self.get_serial_manager(board_name)
        if manager:
            manager.send_receive(message, sendresponse_lambda)
        else:
            print(f"Board {board_name} not found")
            sendresponse_lambda(f"Board {board_name} not found")

class CommandHandler:
    def __init__(self, state_machine: StateMachine, hardware_handler: HardwareHandler):
        self.state_machine = state_machine
        self.hardware_handler = hardware_handler
        self.commands = {
            "get hardware json": self.get_hardware_json,
            "set hardware json": self.set_hardware_json,
            "reload hardware json": self.reload_hardware_json,
            "send_receive": self.send_receive
        }

    def process_message(self, command, socket, addr):
        message_json = json.loads(command)
        command = message_json["command"]
        data = message_json["data"]
        sendresponse_lambda = lambda x : socket.sendto(x.encode('utf-8'), addr)
        if command in self.commands:
            self.commands[command](data, sendresponse_lambda)
        else :
            sendresponse_lambda(f"Unknown command: {command}")
            print(f"Unknown command: {command}")
        

    def get_hardware_json(self, _, sendresponse_lambda):
        sendresponse_lambda(json.dumps(self.hardware_handler.get_config()))
    
    def set_hardware_json(self, data, sendresponse_lambda):
        sendresponse_lambda(self.hardware_handler.set_config(data))

    def reload_hardware_json(self, _, sendresponse_lambda):
        sendresponse_lambda(self.hardware_handler.reload_config())

    def send_receive(self, data, sendresponse_lambda):
        try:
            board_name = data["board_name"]
            message_json = data["message"]
            self.hardware_handler.send_receive(board_name, message_json, sendresponse_lambda)
        except KeyError as e:
            return f"Missing key in data: {e}"  



class UDPServer:
    def __init__(self, command_handler: CommandHandler, host='0.0.0.0', port=8888, print_send=False, print_recieve=False):
        self.command_handler = command_handler
        self.host = host
        self.port = port
        self.print_send = print_send
        self.print_recieve = print_recieve
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
                if self.print_recieve:
                    print(f"UDP Received: '{message}' from {addr}")
                self.command_handler.process_message(message, self.socket, addr)
            except Exception as e:
                if self.running:
                    print(f"UDP Error: {e}")
    
    def stop(self):
        """Stop the server"""
        self.running = False
        self.socket.close()
        print("UDP Server stopped")


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

class TimeKeeper:
    def __init__(self, cycle_time=0.01):
        self.cycle_time = cycle_time
        self.start_time = time.time()
        self.cycle = 0

    def cycle_start(self):
        self.cycle_starttime = time.time()
        

    def cycle_end(self):
        self.cycle += 1
        elapsed = time.time() - self.cycle_starttime
        sleep_time = max(0, self.cycle_time - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

    def get_cycle(self):
        return self.cycle



if __name__ == "__main__":
    deployment_power = False

    state_machine = StateMachine()
    hardware_handler = HardwareHandler()
    command_handler = CommandHandler(state_machine, hardware_handler)
    udp_server = UDPServer(command_handler)
    signal_handler = SignalHandler(udp_server) #To handle system interrupts
    
    print("Startup Complete, waiting for commands")
    time_keeper = TimeKeeper(cycle_time = 0.01)

    try:
        while True:
            time_keeper.cycle_start()

            current_state = state_machine.get_state()
            
            # Perform actions based on current state
            if current_state == MachineStates.IDLE:
                # In IDLE state, just periodic system checks
                #print("IDLE: Performing system health check...")
                # TODO: Implement actual health check
                pass

            elif current_state == MachineStates.ABORT:
                # Flight Termination System - emergency shutdown
                #print("FTS: Executing emergency shutdown procedures...")
                # TODO: Implement actual emergency procedures
                pass

            elif current_state == MachineStates.HOTFIRE:
                # Hot fire test mode
                #print("HOTFIRE: Monitoring engine parameters...")
                # TODO: Implement engine monitoring and control
                pass
                
            elif current_state == MachineStates.LAUNCH:
                # Launch sequence
                #print("LAUNCH: Monitoring launch parameters...")
                # TODO: Implement launch sequence monitoring
                pass

            elif current_state == MachineStates.HOVER:
                # Hover control mode
                #print("HOVER: Running stabilization routines...")
                # TODO: Implement hover control algorithms
                pass
            
            # Sleep to avoid excessive CPU usage
            time_keeper.cycle_end()

    except KeyboardInterrupt:
        signal_handler.handle_signal(signal.SIGINT, None)

'''
TODO
- Look at asyncio
- Current state of each hardware component
- Logging of each state to a csv file (Ability to name it after a test)
- Auto starting and auto requesting of data
- Only send json through if it exists in the hardware configuration, unless unsafe=true
- UDP and serial json logging
Lower priority
- only send actuator commands if deployment power is on


- hardware json to gui

'''

