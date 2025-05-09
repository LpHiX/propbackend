import serial_asyncio
import asyncio
import serial
import time
import json

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
