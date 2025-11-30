"""
Logging configuration for CS2 Arbitrage Bot.
"""

import logging
import sys
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler

from .config import get_config


def setup_logging(level: Optional[str] = None) -> logging.Logger:
    """
    Set up logging with Rich handler for nice terminal output.
    
    Args:
        level: Optional log level override. If not provided, uses config.
        
    Returns:
        The root logger for the cs2arb package.
    """
    config = get_config()
    log_level = level or config.log_level
    
    # Create console for rich output
    console = Console(stderr=True)
    
    # Configure root logger
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                console=console,
                rich_tracebacks=True,
                tracebacks_show_locals=True,
                show_time=True,
                show_path=False,
            )
        ],
    )
    
    # Get our package logger
    logger = logging.getLogger("cs2arb")
    logger.setLevel(log_level)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.
    
    Args:
        name: The module name (usually __name__).
        
    Returns:
        A logger instance.
    """
    return logging.getLogger(name)

