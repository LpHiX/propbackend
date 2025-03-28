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
    def __init__(self, port, baudrate, print_send=False, print_receive=False, emulator=False):
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
        self.loop = asyncio.get_event_loop()

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
            print(f"SERIALMANAGER Serial port {self.port} opened at {self.baudrate} baud")
            
            # Start the background reading thread
            self.running = True

            self.read_task = self.loop.create_task(self._read_loop())
            self.cleanup_task = self.loop.create_task(self._readbuffer_cleanloop())

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
                if line:
                    data = line.decode('utf-8').strip()
                    if data:
                        if self.print_receive:
                            print(f"SERIALMANAGER Received: {data}")
                        try:
                            message_json = json.loads(data)
                            if "send_id" in message_json:
                                async with self.buffer_lock:
                                    self.read_buffer[message_json["send_id"]] = message_json
                                cleanup_time = time.perf_counter() + 1.0  # 1 second timeout
                                async with self.cleanup_lock:
                                    self.cleanup_queue.append((cleanup_time, message_json["send_id"]))
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

    def send_receive(self, message_json, sendresponse_lambda):
        """Send message to serial port (non-blocking)"""
        if not self.writer:
            print("SERIALMANAGER Error: Serial port not open")
        
        self.loop.create_task(self._async_send_receive(message_json, sendresponse_lambda))
        
    async def _async_send_receive(self, message_json, sendresponse_lambda):
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
                        sendresponse_lambda(response)
                        del self.read_buffer[send_id]
                        return
                if time.perf_counter() - start_time > timeout_time:
                    print(f"SERIALMANAGER Timeout waiting for response with send_id {send_id}")
                    sendresponse_lambda(f"SERIALMANAGER Timeout waiting for response with send_id {send_id}")
                    return
                await asyncio.sleep(0.001)
        except Exception as e:
            print(f"SERIALMANAGER Send error: {e}")
            sendresponse_lambda(f"SERIALMANAGER Send error: {e}")
            return

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

class HardwareHandler:
    def __init__(self, emulator=False):
        self.emulator = emulator
        self.serial_managers = {}

        with open('hardware_config.json', 'r') as file:
            self.config = json.load(file)
        with open('hardware_config.json', 'w') as file:
                json.dump(self.config, file, indent=4)

        
    async def initialize(self):
        """Initialize all hardware asynchronously"""
        return await self.load_hardware()
    
    async def load_hardware(self):
        # Initialize serial managers for each board in the configuration
        if 'boards' in self.config:
            for board in self.config['boards']:
                board_name = board['board_name']
                serial_config = board['serial']
                
                if 'port' in serial_config and 'baudrate' in serial_config:
                    try:
                        manager = SerialManager(
                            port=serial_config['port'],
                            baudrate=serial_config['baudrate'],
                            emulator=self.emulator
                        )
                        if await manager.initialize():                        
                            self.serial_managers[board_name] = manager
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
        
    async def reload_config(self):
        """Reload the hardware configuration from a file"""
        self.unload_hardware()  # Unload current hardware configuration
        await self.load_hardware()
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
            "send_receive": self.send_receive,
            "set state": self.state_machine.set_state,
            "get state": self.state_machine.get_state,
        }

    def process_message(self, command, socket, addr):
        message_json = json.loads(command)
        command = message_json["command"]
        data = message_json["data"]
        sendresponse_lambda = lambda x : socket.sendto(x.encode('utf-8'), addr)
        if command in self.commands:
            self.commands[command](data, sendresponse_lambda)
        else:
            sendresponse_lambda(f"Unknown command: {command}")
            print(f"Unknown command: {command}")
        

    def get_hardware_json(self, _, sendresponse_lambda):
        sendresponse_lambda(json.dumps(self.hardware_handler.get_config()))
    
    def set_hardware_json(self, data, sendresponse_lambda):
        sendresponse_lambda(self.hardware_handler.set_config(data))

    async def reload_hardware_json(self, _, sendresponse_lambda):
        sendresponse_lambda(await self.hardware_handler.reload_config())

    def send_receive(self, data, sendresponse_lambda):
        try:
            board_name = data["board_name"]
            message_json = data["message"]
            self.hardware_handler.send_receive(board_name, message_json, sendresponse_lambda)
        except KeyError as e:
            sendresponse_lambda(f"Missing key in data: {e}")

class UDPServer:
    def __init__(self, command_handler: CommandHandler, host='0.0.0.0', port=8888, print_send=False, print_receive=False):
        self.command_handler = command_handler
        self.host = host
        self.port = port
        self.print_send = print_send
        self.print_receive = print_receive

        self.transport = None
        self.protocol = None

        loop = asyncio.get_event_loop()
        loop.create_task(self._start_server())

        print(f"UDP server listening on {self.host}:{self.port}")

    async def _start_server(self):
        """Start the UDP server using asyncio"""
        class UDPServerProtocol(asyncio.DatagramProtocol):
            def __init__(self, server):
                self.server = server
                
            def connection_made(self, transport):
                self.server.transport = transport
                
            def datagram_received(self, data, addr):
                message = data.decode('utf-8').strip()
                if self.server.print_receive:
                    print(f"UDP Received: '{message}' from {addr}")
                
                # Process the message
                self.server.command_handler.process_message(
                    message, 
                    lambda x: self.server.transport.sendto(x.encode('utf-8'), addr),
                    addr
                )
        
        loop = asyncio.get_event_loop()
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
    def __init__(self, udp_server, emulator=False):
        self.udp_server = udp_server
        signal.signal(signal.SIGINT, self.handle_signal)  # Handle Ctrl+C
        signal.signal(signal.SIGTERM, self.handle_signal)  # Handle termination
        if(not emulator):
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
    def __init__(self, cycle_time=0.01, debug_time=0.0):
        self.debug_time = debug_time
        self.cycle_time = cycle_time
        self.start_time = time.perf_counter()
        self.cycle = 0

    def cycle_start(self):
        self.cycle_starttime = time.perf_counter()
        if self.debug_time > 0:
            if(self.cycle % (self.debug_time / self.cycle_time) == 0):
                print(f"Cycle {self.cycle} started at {time.perf_counter() - self.start_time:.5f} seconds")
        

    async def cycle_end(self):
        self.cycle += 1
        next_time = self.start_time + (self.cycle + 1) * self.cycle_time
        await asyncio.sleep(max(0, next_time - time.perf_counter()))  # Sleep for the remaining cycle time


    def get_cycle(self):
        return self.cycle

async def main(emulator=False):
    deployment_power = False

    state_machine = StateMachine()

    hardware_handler = HardwareHandler(emulator=emulator)
    await hardware_handler.initialize()

    command_handler = CommandHandler(state_machine, hardware_handler)
    udp_server = UDPServer(command_handler)
    signal_handler = SignalHandler(udp_server, emulator) #To handle system interrupts
    
    print("Startup Complete, waiting for commands")
    time_keeper = TimeKeeper(cycle_time = 0.01, debug_time = 0.0)

    try:
        while True:
            time_keeper.cycle_start()

            current_state = state_machine.get_state()
            
            # Perform actions based on current state
            if current_state == MachineStates.IDLE:
                pass

            elif current_state == MachineStates.ABORT:
                pass

            elif current_state == MachineStates.HOTFIRE:
                pass
                
            elif current_state == MachineStates.LAUNCH:
                pass

            elif current_state == MachineStates.HOVER:
                pass
            
            # Sleep to avoid excessive CPU usage
            await time_keeper.cycle_end()

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
        print("Running on Windows - standard event loop will be used and using serial emulator")
        asyncio.run(main(emulator=True))
    
    

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

