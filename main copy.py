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
import numpy as np
from scipy.linalg import cholesky
from scipy.spatial.transform import Rotation as R
from proppibackend.state_machine.state_machine import StateMachine













async def main(windows=False, emulator=False):
    deployment_power = False

    state_machine = StateMachine()

    hardware_handler = HardwareHandler(emulator=emulator, debug_prints=False)
    await hardware_handler.initialize()

    command_processor = CommandProcessor(state_machine, hardware_handler)
    udp_server = UDPServer(command_processor, print_send=False, print_receive=False)
    signal_handler = SignalHandler(udp_server, windows) #To handle system interrupts
    
    print("Startup Complete, waiting for commands")
    recurring_taskhandler = RecurringTaskHandler(state_machine, command_processor, hardware_handler)
    command_processor.set_recurring_task_handler(recurring_taskhandler)


    main_loop_time_keeper = TimeKeeper(name="MainLoop", cycle_time=0.01, debug_time=60.0)
    state_machine.set_time_keeper(main_loop_time_keeper)
    
    #main_loop_logger = BoardStateLogger("MainLoop", hardware_handler)
    #main_loop_logger.write_headers(hardware_handler.boards)


    try:
        while True:
            main_loop_time_keeper.cycle_start()

            current_state = state_machine.get_state()

            if state_machine.changing_state:
                main_loop_time_keeper.statechange()     
                state_machine.changing_state = False


            # Perform actions based on current state
            if current_state == MachineStates.STARTTUP:
                if main_loop_time_keeper.time_since_statechange() > 5:
                    state_machine.set_state(MachineStates.IDLE)
                    command_processor.disarm_all(None)
                    print("State changed to IDLE")
            
            elif current_state == MachineStates.IDLE:
                if main_loop_time_keeper.cycle == 0:
                    recurring_taskhandler.set_tasks_idle()
                pass
                    

            elif current_state == MachineStates.ENGINEABORT:
                if main_loop_time_keeper.cycle == 0:
                    recurring_taskhandler.set_tasks_active()

                abort_desiredstates = state_machine.hotfirecontroller.get_abort_desiredstate()
                for board_name, desired_state in abort_desiredstates.items():
                    hardware_handler.update_board_desired_state(board_name, desired_state)

            elif current_state == MachineStates.FTS:
                pass

            elif current_state == MachineStates.HOTFIRE:
                if main_loop_time_keeper.cycle == 0:
                    recurring_taskhandler.set_tasks_active()
                    #hotfire_logger = BoardStateLogger("HotfireLog", hardware_handler)
                    #hotfire_logger.write_headers(hardware_handler.boards)

                
                time_since_statechange = main_loop_time_keeper.time_since_statechange()

                T = state_machine.hotfirecontroller.get_T(time_since_statechange)
                if (main_loop_time_keeper.get_cycle() % 100 == 0):
                    print(f"T{T:.2f}s")
                board_desiredstates = state_machine.hotfirecontroller.get_hotfire_desiredstate(time_since_statechange)
                for board_name, desired_state in board_desiredstates.items():
                    hardware_handler.update_board_desired_state(board_name, desired_state)
                
                #hotfire_logger.write_data(hardware_handler.boards)

                if state_machine.hotfirecontroller.is_hotfire_complete(time_since_statechange):
                    print(f"HOTFIRE COMPLETE at T{T:.2f}s")
                    #hotfire_logger.close()
                    state_machine.set_state(MachineStates.IDLE)
                    main_loop_time_keeper.statechange()
                    command_processor.disarm_all(None)
                    print("State changed to IDLE")
                
            elif current_state == MachineStates.LAUNCH:
                pass

            elif current_state == MachineStates.HOVER:
                states = {}
                for board in hardware_handler.boards:
                    states[board.name] = board.state
                
                #---------------------------------------
                desired_states = {}
                #Implement control system here!!!!!!!!!
                #desired_states = controlsystem(states)
                #---------------------------------------

                hardware_handler = hardware_handler.update_board_desired_state("ActuatorBoard", desired_states)
            
            # Sleep to avoid excessive CPU usage
            #if main_loop_time_keeper.cycle % 10 == 0:
                #main_loop_logger.write_data(hardware_handler.boards)
            await main_loop_time_keeper.cycle_end()

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
        print("Running on Windows - standard event loop will be used")
        asyncio.run(main(windows=True))
    #syncio.run(main(emulator=True))