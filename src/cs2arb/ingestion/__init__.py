"""
Data ingestion modules for CS2 Arbitrage Bot.

Provides functions for fetching and storing market data.
"""

from .buff_prices import ingest_buff_prices_once
from .csfloat_listings import ingest_csfloat_listings_once

__all__ = [
    "ingest_buff_prices_once",
    "ingest_csfloat_listings_once",
]

