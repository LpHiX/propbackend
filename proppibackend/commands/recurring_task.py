class RecurringTask:
    def __init__(self, command_processor: CommandProcessor, name: str, interval: float, command: dict):
        self.command_processor = command_processor
        self.name = name
        self.interval = interval
        self.command = command
        self.timekeeper = TimeKeeper(self.name, cycle_time=interval)
        self.running = True
    async def start_task(self):
        print(f"Starting task: {self.name} with interval {self.interval}")
        #print(json.dumps(self.command, indent=4))
        while self.running:
            self.timekeeper.cycle_start()
            # if(self.command["data"]["board_name"] == "ActuatorBoard"):
            #     print(f"Sending command to actuator board: {json.dumps(self.command)}")
            asyncio.create_task(self.command_processor.process_message(json.dumps(self.command)))
            await self.timekeeper.cycle_end()
    def set_interval(self, interval: float):
        self.interval = interval
        self.timekeeper.set_interval(interval)
        print(f"Task {self.name} interval set to {self.interval}")
    def kill_task(self):
        self.running = False
        print(f"Stopping task: {self.name}")