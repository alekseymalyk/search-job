import logging
import sys
from collections import deque

# We can keep a deque of logs per task
class TaskLogHandler(logging.Handler):
    def __init__(self, task_id, log_dict, maxlen=200):
        super().__init__()
        self.task_id = task_id
        self.log_dict = log_dict
        if task_id not in self.log_dict:
            self.log_dict[task_id] = deque(maxlen=maxlen)

    def emit(self, record):
        msg = self.format(record)
        self.log_dict[self.task_id].append(msg)

def setup_task_logger(task_id, log_dict):
    logger = logging.getLogger(f"task_{task_id}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    
    # Store in memory
    handler = TaskLogHandler(task_id, log_dict)
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Also log to stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)
    
    return logger

def get_task_logger(task_id):
    return logging.getLogger(f"task_{task_id}")
