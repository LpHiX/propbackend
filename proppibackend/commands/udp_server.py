from proppibackend.commands.command_processor import CommandProcessor
import asyncio

class UDPServer:
    def __init__(self, command_processor: CommandProcessor, host='0.0.0.0', port=8888):
        self.command_processor = command_processor
        self.host = host
        self.port = port

        self.transport = None
        self.protocol = None

        asyncio.create_task(self._start_server())

        print(f"UDP server listening on {self.host}:{self.port}")

    async def _start_server(self):
        """Start the UDP server using asyncio"""
        class UDPServerProtocol(asyncio.DatagramProtocol):
            def __init__(self, server: UDPServer):
                self.server = server
                
            def connection_made(self, transport):
                self.server.transport = transport
                
            def datagram_received(self, data, addr):
                message = data.decode('utf-8').strip()
                if self.server.print_receive:
                    print(f"UDP Received: '{message}' from {addr}")
                
                # Process the message
                asyncio.create_task(self._process_message(message, addr))

            async def _process_message(self, message, addr):
                try:
                    response = await self.server.command_processor.process_message(message) 
                    self.server.transport.sendto(response.encode('utf-8'), addr)
                except Exception as e:
                    print(f"Error processing message: {e}")
                    error_response = f"Error processing message: {e}"
                    self.server.transport.sendto(error_response.encode('utf-8'), addr)
        
        loop = asyncio.get_running_loop()
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: UDPServerProtocol(self),
            local_addr=(self.host, self.port)
        )
    
    def stop(self):
        """Stop the server"""
        if self.transport:
            self.transport.close()
        print("UDP Server stopped")