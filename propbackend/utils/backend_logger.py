import logging
import os
import sys
from datetime import datetime
from typing import Optional

class _BackendLoggerSingleton:
    _instance: Optional['_BackendLoggerSingleton'] = None
    _logger: Optional[logging.Logger] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(_BackendLoggerSingleton, cls).__new__(cls)
            cls._instance._initialize_logger()
        return cls._instance
    
    def _initialize_logger(self) -> None:
        """Initialize the logger with console and file handlers"""
        self._logger = logging.getLogger('backend_logger')
        self._logger.setLevel(logging.DEBUG)
        self._logger.propagate = False
        
        # Clear any existing handlers
        if self._logger.hasHandlers():
            self._logger.handlers.clear()
        
        # Create console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)

        class ColorFormatter(logging.Formatter):
            RED = '\033[91m'
            RESET = '\033[0m'
            FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

            def format(self, record):
                log_fmt = self.FORMAT
                if record.levelno == logging.ERROR or record.levelno == logging.CRITICAL:
                    log_fmt = self.RED + self.FORMAT + self.RESET
                formatter = logging.Formatter(log_fmt)
                return formatter.format(record)

        console_handler.setFormatter(ColorFormatter())

        self._logger.addHandler(console_handler)

        
        # # Create file handler
        # log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        # os.makedirs(log_dir, exist_ok=True)
        # timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        # log_file = os.path.join(log_dir, f'backend_logger_{timestamp}.log')
        
        # file_handler = logging.FileHandler(log_file)
        # file_handler.setLevel(logging.DEBUG)
        # file_format = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
        # file_handler.setFormatter(file_format)
        # self._logger.addHandler(file_handler)
    
    def debug(self, message: str) -> None:
        """Log a debug message"""
        self._logger.debug(message)
    
    def info(self, message: str) -> None:
        """Log an info message"""
        self._logger.info(message)
    
    def warning(self, message: str) -> None:
        """Log a warning message"""
        self._logger.warning(message)
    
    def error(self, message: str) -> None:
        """Log an error message"""
        self._logger.error(message)
    
    def critical(self, message: str) -> None:
        """Log a critical message"""
        self._logger.critical(message)
    
    def exception(self, message: str) -> None:
        """Log an exception with traceback"""
        self._logger.exception(message)

# Create the singleton instance with the specific name 'backend_logger'
backend_logger = _BackendLoggerSingleton()