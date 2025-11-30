"""
Core business logic for CS2 Arbitrage Bot.

Provides arbitrage computation and watchlist management.
"""

from .arbitrage_engine import (
    compute_buff_to_csfloat_signals,
    compute_csfloat_to_buff_signals,
)
from .watchlist import Watchlist, get_default_watchlist

__all__ = [
    "compute_csfloat_to_buff_signals",
    "compute_buff_to_csfloat_signals",
    "Watchlist",
    "get_default_watchlist",
]

