"""
Watchlist management for CS2 Arbitrage Bot.

Maintains a list of items to monitor for Buff → CSFloat arbitrage.
"""

import json
from pathlib import Path
from typing import Optional

from ..config import PROJECT_ROOT
from ..logging_config import get_logger

logger = get_logger(__name__)


# Default high-volume items to watch for Buff → CSFloat
DEFAULT_WATCHLIST_ITEMS = [
    # Popular AK-47 skins
    "AK-47 | Case Hardened (Field-Tested)",
    "AK-47 | Case Hardened (Minimal Wear)",
    "AK-47 | Case Hardened (Well-Worn)",
    "AK-47 | Case Hardened (Factory New)",
    "AK-47 | Case Hardened (Battle-Scarred)",
    "AK-47 | Redline (Field-Tested)",
    "AK-47 | Asiimov (Field-Tested)",
    "AK-47 | Asiimov (Battle-Scarred)",
    "AK-47 | Vulcan (Factory New)",
    "AK-47 | Vulcan (Minimal Wear)",
    "AK-47 | Vulcan (Field-Tested)",
    
    # Popular AWP skins
    "AWP | Asiimov (Field-Tested)",
    "AWP | Asiimov (Battle-Scarred)",
    "AWP | Asiimov (Well-Worn)",
    "AWP | Lightning Strike (Factory New)",
    "AWP | Dragon Lore (Field-Tested)",
    "AWP | Dragon Lore (Minimal Wear)",
    "AWP | Dragon Lore (Factory New)",
    
    # Popular M4A4 skins
    "M4A4 | Howl (Field-Tested)",
    "M4A4 | Howl (Minimal Wear)",
    "M4A4 | Howl (Factory New)",
    "M4A4 | Asiimov (Field-Tested)",
    
    # Popular knives (Karambit)
    "★ Karambit | Case Hardened (Field-Tested)",
    "★ Karambit | Case Hardened (Minimal Wear)",
    "★ Karambit | Case Hardened (Well-Worn)",
    "★ Karambit | Case Hardened (Factory New)",
    "★ Karambit | Doppler (Factory New)",
    "★ Karambit | Fade (Factory New)",
    "★ Karambit | Tiger Tooth (Factory New)",
    "★ Karambit | Marble Fade (Factory New)",
    
    # Popular knives (Butterfly)
    "★ Butterfly Knife | Case Hardened (Field-Tested)",
    "★ Butterfly Knife | Case Hardened (Minimal Wear)",
    "★ Butterfly Knife | Doppler (Factory New)",
    "★ Butterfly Knife | Fade (Factory New)",
    
    # Popular gloves
    "★ Sport Gloves | Pandora's Box (Field-Tested)",
    "★ Sport Gloves | Pandora's Box (Minimal Wear)",
    "★ Specialist Gloves | Crimson Kimono (Field-Tested)",
    "★ Specialist Gloves | Crimson Kimono (Minimal Wear)",
]


class Watchlist:
    """
    Manages a list of items to watch for arbitrage opportunities.
    
    Items in the watchlist are checked for Buff → CSFloat arbitrage.
    """
    
    def __init__(self, items: Optional[list[str]] = None):
        """
        Initialize the watchlist.
        
        Args:
            items: Optional list of market hash names.
        """
        self.items: list[str] = items or []
    
    def add(self, market_hash_name: str) -> None:
        """Add an item to the watchlist."""
        if market_hash_name not in self.items:
            self.items.append(market_hash_name)
            logger.info(f"Added to watchlist: {market_hash_name}")
    
    def remove(self, market_hash_name: str) -> bool:
        """Remove an item from the watchlist."""
        if market_hash_name in self.items:
            self.items.remove(market_hash_name)
            logger.info(f"Removed from watchlist: {market_hash_name}")
            return True
        return False
    
    def contains(self, market_hash_name: str) -> bool:
        """Check if an item is in the watchlist."""
        return market_hash_name in self.items
    
    def clear(self) -> None:
        """Clear all items from the watchlist."""
        self.items.clear()
        logger.info("Cleared watchlist")
    
    def save(self, path: Optional[Path] = None) -> None:
        """
        Save the watchlist to a JSON file.
        
        Args:
            path: Optional path. Defaults to data/watchlist.json.
        """
        if path is None:
            path = PROJECT_ROOT / "data" / "watchlist.json"
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"items": self.items}, f, indent=2)
        
        logger.info(f"Saved watchlist to {path}")
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Watchlist":
        """
        Load a watchlist from a JSON file.
        
        Args:
            path: Optional path. Defaults to data/watchlist.json.
            
        Returns:
            Loaded Watchlist instance.
        """
        if path is None:
            path = PROJECT_ROOT / "data" / "watchlist.json"
        
        if not path.exists():
            logger.debug(f"No watchlist file at {path}, returning empty")
            return cls()
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        items = data.get("items", [])
        logger.info(f"Loaded {len(items)} items from watchlist")
        return cls(items=items)
    
    def __len__(self) -> int:
        return len(self.items)
    
    def __iter__(self):
        return iter(self.items)
    
    def __repr__(self) -> str:
        return f"<Watchlist({len(self.items)} items)>"


def get_default_watchlist() -> Watchlist:
    """
    Get the default watchlist.
    
    Tries to load from file, falls back to built-in defaults.
    
    Returns:
        Watchlist instance.
    """
    watchlist_path = PROJECT_ROOT / "data" / "watchlist.json"
    
    if watchlist_path.exists():
        try:
            return Watchlist.load(watchlist_path)
        except Exception as e:
            logger.warning(f"Failed to load watchlist: {e}")
    
    return Watchlist(items=DEFAULT_WATCHLIST_ITEMS.copy())

