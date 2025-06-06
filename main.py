import asyncio
import platform
import signal

from propbackend.state_machine.state_machine import StateMachine
from propbackend.utils.signal_handler import SignalHandler
from propbackend.utils import backend_logger
from propbackend.commands.udp_server import UDPServer
from propbackend.commands.command_processor import CommandProcessor
from propbackend.hardware.hardware_handler import HardwareHandler

from propbackend.utils.boardstate_logger import BoardStateLogger

def try_uvloop() -> None:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        backend_logger.critical("uvloop not available. Run: pip install uvloop for better performance")

async def main() -> None:
    hardware_handler = HardwareHandler()
    await hardware_handler.initialize()

    command_processor = CommandProcessor()
    state_machine = StateMachine(hardware_handler)
    udp_server = UDPServer(command_processor)

    command_processor.initialise(state_machine, hardware_handler)
    
    signal_handler = SignalHandler(udp_server)
        
    #signal_handler.add_shutdown_task(lambda: debug_logger.info("Shutting down state machine..."))


    main_loop_logger = BoardStateLogger("mainloop", hardware_handler)
    main_loop_logger.write_headers(hardware_handler.boards)

    try:
        while True:
            await state_machine.main_loop()
            if state_machine.time_keeper.get_cycle() % 10 == 0:
                main_loop_logger.write_data(hardware_handler.boards)
    except asyncio.CancelledError:
        # This will be reached when tasks are cancelled during shutdown
        backend_logger.info("Main loop cancelled, shutting down...")
    except KeyboardInterrupt:
        # Fallback if the signal handler doesn't catch it
        backend_logger.info("KeyboardInterrupt caught in main(), shutting down...")
        signal_handler.handle_signal(signal.SIGINT, None)

if __name__ == "__main__":
    backend_logger.info("=====================Starting backend...======================")
    if platform.system() != "Windows":
        try_uvloop()
        #debug_logger.info("Running on non-Windows - using uvloop for enhanced performance")
    else:
        pass
        #debug_logger.info("Running on Windows - standard event loop will be used")

    asyncio.run(main())