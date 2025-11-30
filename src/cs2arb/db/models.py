"""
SQLAlchemy models for CS2 Arbitrage Bot.

Defines the database schema for storing market data and arbitrage signals.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class ArbitrageDirection(enum.Enum):
    """Direction of arbitrage opportunity."""
    CSFLOAT_TO_BUFF = "CSFLOAT_TO_BUFF"
    BUFF_TO_CSFLOAT = "BUFF_TO_CSFLOAT"


class BuffItem(Base):
    """
    Represents a Buff163 item (skin).
    
    Stores the basic info about each item we track from Buff.
    """
    __tablename__ = "buff_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goods_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    market_hash_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Optional parsed fields
    weapon: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    skin_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    wear: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Timestamps
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    price_snapshots: Mapped[list["BuffPriceSnapshot"]] = relationship(
        "BuffPriceSnapshot", back_populates="item", cascade="all, delete-orphan"
    )
    signals: Mapped[list["ArbitrageSignal"]] = relationship(
        "ArbitrageSignal", back_populates="buff_item"
    )

    def __repr__(self) -> str:
        return f"<BuffItem(goods_id={self.goods_id}, name='{self.market_hash_name}')>"


class BuffPriceSnapshot(Base):
    """
    Represents a point-in-time snapshot of Buff163 floor prices.
    
    Captures the global floor price and tag-specific floors for an item.
    """
    __tablename__ = "buff_price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )
    goods_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("buff_items.goods_id"), nullable=False, index=True
    )
    
    # Price in CNY
    overall_min_price: Mapped[float] = mapped_column(Float, nullable=False)
    
    # JSON blob for tag-specific floors (e.g., by sticker, by float tier)
    # Stored as TEXT since SQLite doesn't have native JSON
    tag_floors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Stat time from API (Unix timestamp or datetime)
    stat_time: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Whether this item is within our target price band
    within_target_range: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    item: Mapped["BuffItem"] = relationship("BuffItem", back_populates="price_snapshots")

    def __repr__(self) -> str:
        return f"<BuffPriceSnapshot(goods_id={self.goods_id}, price={self.overall_min_price} CNY)>"


class CSFloatListing(Base):
    """
    Represents an individual CSFloat listing.
    
    Stores listings we've seen, especially high-discount buy-now listings.
    """
    __tablename__ = "csfloat_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    csfloat_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    market_hash_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Price in cents (USD)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Discount as reported by CSFloat (e.g., 0.15 = 15% discount)
    discount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Listing type
    listing_type: Mapped[str] = mapped_column(String(50), default="buy_now")
    
    # Item details
    float_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    paint_seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    wear_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Sticker info (JSON blob)
    stickers_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Volume/liquidity indicators
    reference_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    watchers: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Tracking
    seen_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    signals: Mapped[list["ArbitrageSignal"]] = relationship(
        "ArbitrageSignal", back_populates="csfloat_listing"
    )

    @property
    def price_usd(self) -> float:
        """Get price in USD."""
        return self.price_cents / 100.0

    def __repr__(self) -> str:
        return f"<CSFloatListing(id='{self.csfloat_id}', name='{self.market_hash_name}', ${self.price_usd:.2f})>"


class ArbitrageSignal(Base):
    """
    Represents an arbitrage opportunity we've computed.
    
    Stores the details of a potential profitable trade between markets.
    """
    __tablename__ = "arbitrage_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Direction of the arbitrage
    direction: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    
    # Item identification
    market_hash_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    buff_goods_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("buff_items.goods_id"), nullable=True
    )
    csfloat_listing_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("csfloat_listings.id"), nullable=True
    )
    
    # Price data
    buff_floor_cny: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    buff_floor_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    csfloat_price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Computed ROI
    roi_pct: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, index=True
    )
    
    # Manual notes
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Status tracking
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    acted_on: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relationships
    buff_item: Mapped[Optional["BuffItem"]] = relationship(
        "BuffItem", back_populates="signals"
    )
    csfloat_listing: Mapped[Optional["CSFloatListing"]] = relationship(
        "CSFloatListing", back_populates="signals"
    )
    trades: Mapped[list["Trade"]] = relationship(
        "Trade", back_populates="signal"
    )

    def __repr__(self) -> str:
        return f"<ArbitrageSignal(direction={self.direction}, item='{self.market_hash_name}', ROI={self.roi_pct:.1%})>"


class Trade(Base):
    """
    Represents an executed trade.
    
    Allows manual logging of trades for tracking actual P&L.
    """
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Link to signal if trade was based on one
    signal_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("arbitrage_signals.id"), nullable=True
    )
    
    # Trade details
    market_hash_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(50), nullable=False)
    buy_market: Mapped[str] = mapped_column(String(50), nullable=False)
    sell_market: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Prices in USD
    buy_price_usd: Mapped[float] = mapped_column(Float, nullable=False)
    sell_price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Timestamps
    buy_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    sell_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Notes
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    signal: Mapped[Optional["ArbitrageSignal"]] = relationship(
        "ArbitrageSignal", back_populates="trades"
    )

    @property
    def roi_pct(self) -> Optional[float]:
        """Compute ROI if we have both buy and sell prices."""
        if self.sell_price_usd is None:
            return None
        return (self.sell_price_usd - self.buy_price_usd) / self.buy_price_usd

    @property
    def profit_usd(self) -> Optional[float]:
        """Compute profit in USD."""
        if self.sell_price_usd is None:
            return None
        return self.sell_price_usd - self.buy_price_usd

    @property
    def hold_days(self) -> Optional[int]:
        """Compute days held."""
        if self.sell_time is None:
            return None
        return (self.sell_time - self.buy_time).days

    def __repr__(self) -> str:
        status = "OPEN" if self.sell_price_usd is None else f"CLOSED (ROI: {self.roi_pct:.1%})"
        return f"<Trade(item='{self.market_hash_name}', {status})>"

