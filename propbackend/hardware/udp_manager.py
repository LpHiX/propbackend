import asyncio
import json
import socket
import time

from propbackend.utils.config_reader import config_reader
from propbackend.utils import backend_logger

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from propbackend.hardware.board import Board

class UDPManager:
    def __init__(self, board: "Board", ip, port):
        self.board = board
        self.ip = ip
        self.port = port
        self.running = False

        self.read_buffer = {}
        self.buffer_lock = asyncio.Lock()
        self.send_id = 0
        self.send_id_lock = asyncio.Lock()

        self.cleanup_queue = []  # Will store (timestamp, id) tuples
        self.cleanup_lock = asyncio.Lock()

        # This is why all three are required:
        # - Send_recieve queues a message to be read, and waits for a read buffer
        # - Read_loop reads from the UDP socket and puts it in the read buffer
        # - Readbuffer_cleanloop cleans up the read buffer

        self.transport = None
        self.protocol = None

    async def initialize(self):
        """Initialize the UDP connection"""        
        try:
            loop = asyncio.get_running_loop()
            
            # Create UDP endpoint
            class UDPClientProtocol(asyncio.DatagramProtocol):
                def __init__(self, manager):
                    self.manager = manager
                
                def connection_made(self, transport):
                    pass
                
                def datagram_received(self, data, addr):
                    asyncio.create_task(self.manager._process_datagram(data, addr))
                
                def error_received(self, exc):
                    backend_logger.error(f"UDPMANAGER Protocol error: {exc}")
                
                def connection_lost(self, exc):
                    if exc:
                        backend_logger.error(f"UDPMANAGER Connection lost: {exc}")
            
            self.transport, self.protocol = await loop.create_datagram_endpoint(
                lambda: UDPClientProtocol(self),
                remote_addr=(self.ip, self.port)
            )
            
            backend_logger.info(f"UDPMANAGER UDP connection established to {self.ip}:{self.port} for board {self.board.name}")
            
            # Start the background tasks
            self.running = True
            self.cleanup_task = asyncio.create_task(self._readbuffer_cleanloop())

            return True
            
        except Exception as e:
            backend_logger.error(f"UDPMANAGER Error establishing UDP connection to {self.ip}:{self.port}: {e}")
            self.transport = None
            return False

    async def _process_datagram(self, data, addr):
        """Process received UDP datagrams"""
        try:
            data_str = data.decode('utf-8').strip()
            if not data_str:
                return

            backend_logger.debug(f"UDPMESSAGE Received: {data_str}")

            try:
                message_json = json.loads(data_str)
                if "send_id" in message_json:
                    send_id = message_json["send_id"]
                    async with self.buffer_lock:
                        self.read_buffer[send_id] = message_json

                    cleanup_time = time.perf_counter() + 1.0  # 1 second timeout
                    async with self.cleanup_lock:
                        self.cleanup_queue.append((cleanup_time, send_id))
            except json.JSONDecodeError:
                backend_logger.error(f"UDPMANAGER JSON Decode error: {data_str}")
        except Exception as e:
            backend_logger.error(f"UDPMANAGER Process datagram error: {e}")

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
                                    backend_logger.debug(f"UDPMANAGER Cleanup: Removing message with send_id {cleanup_id}")
                                    del self.read_buffer[cleanup_id]
                        
                        if self.cleanup_queue:
                            next_cleanup_time = self.cleanup_queue[0][0]
                if next_cleanup_time is not None:
                    await asyncio.sleep(max(0.1, next_cleanup_time - time.perf_counter()))
                else:
                    await asyncio.sleep(0.1)
            except Exception as e:
                backend_logger.error(f"UDPMANAGER Cleanup error: {e}")
                await asyncio.sleep(0.1)

    async def send_receive(self, message_json:dict) -> None:
        """Send message to UDP socket and wait for response"""
        if not self.transport:
            backend_logger.error("UDPMANAGER Error: UDP connection not established")
            return None
        try:
            async with self.send_id_lock:
                send_id = self.send_id
                self.send_id += 1
            message_json["send_id"] = send_id
            message = json.dumps(message_json)

            backend_logger.debug(f"UDPMESSAGE Sending: {message.strip()}")
            self.transport.sendto(message.encode('utf-8'), (self.ip, self.port))

            start_time = time.perf_counter()
            timeout_time = 1.0  # 1 second timeout
            while time.perf_counter() - start_time < timeout_time:
                async with self.buffer_lock:
                    if send_id in self.read_buffer:
                        response = json.dumps(self.read_buffer[send_id])
                        del self.read_buffer[send_id]
                        response_json = json.loads(response)
                        self.board.update_state(response_json)
                        break
                await asyncio.sleep(0.001)
            if time.perf_counter() - start_time > timeout_time:
                backend_logger.warning(f"UDPMESSAGE Timeout waiting for response with send_id {send_id} for board {self.board.name}")
        except json.JSONDecodeError as e:
            backend_logger.error(f"UDPMANAGER JSON Decode error: {e}")
        except Exception as e:
            backend_logger.error(f"UDPMANAGER Send_receive error: {e}", exc_info=True)

    def is_connected(self):
        """Check if UDP connection is active"""
        return self.transport is not None
        
    def close(self):
        """Close the UDP connection gracefully"""
        self.running = False

        if hasattr(self, 'cleanup_task'):
            self.cleanup_task.cancel()

        if self.transport:
            self.transport.close()
            backend_logger.info(f"UDPMANAGER UDP connection to {self.ip}:{self.port} closed")