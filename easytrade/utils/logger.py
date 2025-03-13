"""
Utility functions for logging.
"""
import logging
import os
import sys
from datetime import datetime


def setup_logger(name: str = None, log_level: int = logging.INFO,
                log_file: str = None, console_output: bool = True) -> logging.Logger:
    """
    Set up a logger with the specified configuration.
    
    Args:
        name: Logger name (defaults to root logger)
        log_level: Logging level (defaults to INFO)
        log_file: Path to log file (optional)
        console_output: Whether to output logs to console
        
    Returns:
        Configured logger
    """
    # Get logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Add file handler if specified
    if log_file:
        # Create directory if it doesn't exist
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
    # Add console handler if specified
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
    return logger


def setup_trading_logger(strategy_name: str, log_dir: str = 'logs') -> logging.Logger:
    """
    Set up a logger specifically for trading strategies.
    
    Args:
        strategy_name: Name of the strategy
        log_dir: Directory to store log files
        
    Returns:
        Configured logger
    """
    # Create log directory if it doesn't exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    # Create log file name with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f"{strategy_name}_{timestamp}.log")
    
    # Set up logger
    return setup_logger(
        name=strategy_name,
        log_level=logging.INFO,
        log_file=log_file,
        console_output=True
    ) 