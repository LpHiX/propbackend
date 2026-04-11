import sys
import signal
import os
import platform


class SignalHandler:
    def __init__(self, udp_server):
        self.udp_server = udp_server
        self.shutdown_tasks = []
        signal.signal(signal.SIGINT, self.handle_signal)  # Handle Ctrl+C
        signal.signal(signal.SIGTERM, self.handle_signal)  # Handle termination
        if(platform.system() != "Windows"):
            signal.signal(signal.SIGTSTP, self.handle_suspend)

    def add_shutdown_task(self, task):
        self.shutdown_tasks.append(task)

    def handle_signal(self, signum, frame):
        print(f"Received signal {signum}, stopping server...")
        for task in self.shutdown_tasks:
            try:
                task()
            except Exception as exc:
                print(f"Shutdown task failed: {exc}")
        #self.udp_server.stop()
        sys.exit(0)

    def handle_suspend(self, signum, frame):
        """Handle process suspension (Ctrl+Z)"""
        print("\nProcess being suspended, cleaning up resources...")
        #self.udp_server.stop()
        # Re-raise SIGTSTP to actually suspend after cleanup
        signal.signal(signal.SIGTSTP, signal.SIG_DFL)
        os.kill(os.getpid(), signal.SIGTSTP)