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
import csv
from datetime import datetime
import copy
#import numpy as np
#from scipy.linalg import cholesky
#from scipy.spatial.transform import Rotation as R
from proppibackend.state_machine.state_machine import StateMachine
from proppibackend.utils.signal_handler import SignalHandler
from proppibackend.utils import debug_logger

def try_uvloop() -> bool:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        print("Using uvloop for enhanced performance")
    except ImportError:
        print("uvloop not available. Run: pip install uvloop for better performance")

async def main() -> None:
    state_machine = StateMachine()
    signal_handler = SignalHandler(None)
        
    #signal_handler.add_shutdown_task(lambda: debug_logger.info("Shutting down state machine..."))
    
    try:
        while True:
            await state_machine.main_loop()
    except asyncio.CancelledError:
        # This will be reached when tasks are cancelled during shutdown
        debug_logger.info("Main loop cancelled, shutting down...")
    except KeyboardInterrupt:
        # Fallback if the signal handler doesn't catch it
        debug_logger.info("KeyboardInterrupt caught in main(), shutting down...")
        signal_handler.handle_sigint()

if __name__ == "__main__":
    debug_logger.info("=====================Starting backend...======================")
    if platform.system() != "Windows":
        try_uvloop()
        debug_logger.info("Running on non-Windows - using uvloop for enhanced performance")
    else:
        debug_logger.info("Running on Windows - standard event loop will be used")

    asyncio.run(main())