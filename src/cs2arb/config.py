"""
Configuration management for CS2 Arbitrage Bot.

Loads configuration from:
- .env file (API keys only - sensitive)
- config.yaml (all other settings - editable by Cursor)
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


# Load .env file from project root
def _find_project_root() -> Path:
    """Find the project root directory by looking for pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / "pyproject.toml").exists():
            return current
        current = current.parent
    # Fallback to src parent
    return Path(__file__).resolve().parent.parent.parent


PROJECT_ROOT = _find_project_root()
load_dotenv(PROJECT_ROOT / ".env", override=True)


def _load_yaml_config() -> dict[str, Any]:
    """Load configuration from config.yaml."""
    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class Config(BaseModel):
    """Application configuration."""

    # Buff163 API (from .env)
    buff_api_key: str = Field(default="")
    buff_api_base_url: str = Field(default="https://buff.163.com")
    buff_session_cookie: Optional[str] = Field(default=None)

    # CSFloat API (from .env)
    csfloat_api_key: str = Field(default="")
    csfloat_api_base_url: str = Field(default="https://csfloat.com")

    # Exchange rate
    fx_cny_to_usd: float = Field(default=0.14)

    # Fees (as decimals)
    buff_sell_fee_pct: float = Field(default=0.025)
    csfloat_buy_fee_pct: float = Field(default=0.0)
    csfloat_sell_fee_pct: float = Field(default=0.02)

    # Price range (USD)
    min_price_usd: float = Field(default=100.0)
    max_price_usd: float = Field(default=1500.0)

    # ROI thresholds
    min_roi_csfloat_to_buff: float = Field(default=0.08)
    min_roi_buff_to_csfloat: float = Field(default=0.10)

    # Volume/liquidity filters
    min_csfloat_listings: int = Field(default=5)
    min_watchers: int = Field(default=0)
    
    # Item type filters
    allowed_item_types: list[str] = Field(default_factory=lambda: ["weapon", "knife", "gloves"])

    # Scanning intervals
    buff_scan_interval_seconds: int = Field(default=600)
    csfloat_scan_interval_seconds: int = Field(default=30)
    csfloat_pages_to_fetch: int = Field(default=10)
    csfloat_min_discount: float = Field(default=0.0)

    # Database
    database_path: str = Field(default="data/cs2arb.db")

    # Logging
    log_level: str = Field(default="INFO")

    @property
    def database_url(self) -> str:
        """Get the SQLite database URL."""
        db_path = PROJECT_ROOT / self.database_path
        return f"sqlite:///{db_path}"

    @property
    def database_file_path(self) -> Path:
        """Get the database file path."""
        return PROJECT_ROOT / self.database_path


def load_config() -> Config:
    """Load configuration from .env (API keys) and config.yaml (settings)."""
    # Load YAML config first
    yaml_config = _load_yaml_config()
    
    # Build config with YAML values, falling back to defaults
    return Config(
        # API keys from .env only (sensitive)
        buff_api_key=os.getenv("BUFF_API_KEY", ""),
        buff_session_cookie=os.getenv("BUFF_SESSION_COOKIE"),
        csfloat_api_key=os.getenv("CSFLOAT_API_KEY", ""),
        
        # API base URLs from config.yaml
        buff_api_base_url=yaml_config.get("buff_api_base_url", "https://buff.163.com"),
        csfloat_api_base_url=yaml_config.get("csfloat_api_base_url", "https://csfloat.com"),
        
        # Everything else from config.yaml
        fx_cny_to_usd=float(yaml_config.get("fx_cny_to_usd", 0.14)),
        buff_sell_fee_pct=float(yaml_config.get("buff_sell_fee_pct", 0.025)),
        csfloat_buy_fee_pct=float(yaml_config.get("csfloat_buy_fee_pct", 0.0)),
        csfloat_sell_fee_pct=float(yaml_config.get("csfloat_sell_fee_pct", 0.02)),
        min_price_usd=float(yaml_config.get("min_price_usd", 100)),
        max_price_usd=float(yaml_config.get("max_price_usd", 1500)),
        min_roi_csfloat_to_buff=float(yaml_config.get("min_roi_csfloat_to_buff", 0.08)),
        min_roi_buff_to_csfloat=float(yaml_config.get("min_roi_buff_to_csfloat", 0.10)),
        min_csfloat_listings=int(yaml_config.get("min_csfloat_listings", 5)),
        min_watchers=int(yaml_config.get("min_watchers", 0)),
        allowed_item_types=yaml_config.get("allowed_item_types", ["weapon", "knife", "gloves"]),
        buff_scan_interval_seconds=int(yaml_config.get("buff_scan_interval_seconds", 600)),
        csfloat_scan_interval_seconds=int(yaml_config.get("csfloat_scan_interval_seconds", 30)),
        csfloat_pages_to_fetch=int(yaml_config.get("csfloat_pages_to_fetch", 10)),
        csfloat_min_discount=float(yaml_config.get("csfloat_min_discount", 0.0)),
        database_path=yaml_config.get("database_path", "data/cs2arb.db"),
        log_level=yaml_config.get("log_level", "INFO"),
    )


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config

