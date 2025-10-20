import logging
import os
from datetime import datetime

def setup_logger(name: str = 'upbit_trader', level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)
    
    log_filename = f"{log_dir}/trading_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logger()