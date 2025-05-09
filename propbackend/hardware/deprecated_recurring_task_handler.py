

class RecurringTaskHandler:
    def __init__(self, command_processor: CommandProcessor):
        self.command_processor = command_processor
        self.recurring_tasks: list[RecurringTask] = []

        if state_machine.get_state() == MachineStates.STARTTUP:
            self.on_machine_startup()

    def on_machine_startup(self):
        for recurring_task in self.recurring_tasks:
            recurring_task.kill_task()

        self.recurring_tasks = self.command_processor.get_startup_tasks(self.command_processor)
        for recurring_task in self.recurring_tasks:
            asyncio.create_task(recurring_task.start_task())

        if self.state_machine.get_state() == MachineStates.IDLE:
            self.set_tasks_idle()

    def set_tasks_idle(self):
        for board in self.hardware_handler.boards:
            idle_interval = board.config["idle_interval"]
            recurring_task = self.get_recurring_task(f'{board.name}_MainTask')
            if recurring_task:
                recurring_task.set_interval(idle_interval)

    def set_tasks_active(self):
        for board in self.hardware_handler.boards:
            active_interval = board.config["active_interval"]
            recurring_task = self.get_recurring_task(f'{board.name}_MainTask')
            if recurring_task:
                recurring_task.set_interval(active_interval)

    def stop_task(self, task):
        task.kill_task()

    def get_recurring_task(self, recurring_task_name) -> RecurringTask:
        for recurring_task in self.recurring_tasks:
            if recurring_task.name == recurring_task_name:
                return recurring_task
        return None

    def get_tasks(self) -> list[RecurringTask]:
        return self.recurring_tasks

