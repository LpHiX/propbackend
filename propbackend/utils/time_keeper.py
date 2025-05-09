import asyncio
import time
from propbackend.utils import backend_logger

class TimeKeeper:
    def __init__(self, name, cycle_time, debug_time=0.0):
        self.name = name
        self.debug_time = debug_time
        self.cycle_time = cycle_time
        self.start_time = time.perf_counter()
        self.statechange_time = self.start_time
        self.cycle = 0

    def set_interval(self, cycle_time):
        self.cycle_time = cycle_time
        self.cycle = 0
        self.statechange_time = time.perf_counter()

    def cycle_start(self):
        self.cycle_starttime = time.perf_counter()
        if self.debug_time > 0:
            if(self.cycle % (self.debug_time / self.cycle_time) == 0):
                backend_logger.debug(f"TimeKeeper {self.name} is at cycle {self.cycle} at {time.perf_counter() - self.start_time:.5f} seconds")

    def time_since_start(self) -> float:
        return time.perf_counter() - self.start_time
    
    def statechange(self) -> None:
        self.cycle = 0
        self.statechange_time = time.perf_counter()

    def time_since_statechange(self) -> float:
        return time.perf_counter() - self.statechange_time

    async def cycle_end(self):
        self.cycle += 1
        next_time = self.statechange_time + (self.cycle + 1) * self.cycle_time
        await asyncio.sleep(max(0, next_time - time.perf_counter()))  # Sleep for the remaining cycle time


    def get_cycle(self):
        return self.cycle