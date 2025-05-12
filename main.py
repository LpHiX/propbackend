import asyncio
import platform

from propbackend.state_machine.state_machine import StateMachine
from propbackend.utils.signal_handler import SignalHandler
from propbackend.utils import backend_logger
from propbackend.commands.udp_server import UDPServer
from propbackend.commands.command_processor import CommandProcessor
from propbackend.hardware.hardware_handler import HardwareHandler

def try_uvloop() -> bool:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        backend_logger.critical("uvloop not available. Run: pip install uvloop for better performance")

async def main() -> None:
    hardware_handler = HardwareHandler()
    await hardware_handler.initialize()

    command_processor = CommandProcessor()
    state_machine = StateMachine(command_processor)
    udp_server = UDPServer(command_processor)

    command_processor.initialise(state_machine, hardware_handler)
    
    signal_handler = SignalHandler(udp_server)
        
    #signal_handler.add_shutdown_task(lambda: debug_logger.info("Shutting down state machine..."))
    

    try:
        while True:
            await state_machine.main_loop()
    except asyncio.CancelledError:
        # This will be reached when tasks are cancelled during shutdown
        backend_logger.info("Main loop cancelled, shutting down...")
    except KeyboardInterrupt:
        # Fallback if the signal handler doesn't catch it
        backend_logger.info("KeyboardInterrupt caught in main(), shutting down...")
        signal_handler.handle_sigint()

if __name__ == "__main__":
    backend_logger.info("=====================Starting backend...======================")
    if platform.system() != "Windows":
        try_uvloop()
        #debug_logger.info("Running on non-Windows - using uvloop for enhanced performance")
    else:
        pass
        #debug_logger.info("Running on Windows - standard event loop will be used")

    asyncio.run(main())