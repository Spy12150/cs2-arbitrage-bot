"""
Buff163 price ingestion.

Fetches and stores Buff floor prices into the database.
"""

import json
import re
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..clients.buff_client import BuffClient, BuffItemDTO
from ..config import Config, get_config
from ..db.models import BuffItem, BuffPriceSnapshot
from ..logging_config import get_logger

logger = get_logger(__name__)


def parse_item_name(market_hash_name: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Parse a market hash name into weapon, skin, and wear.
    
    Args:
        market_hash_name: e.g., "AK-47 | Case Hardened (Field-Tested)"
        
    Returns:
        Tuple of (weapon, skin_name, wear).
    """
    # Pattern: "Weapon | Skin Name (Wear)"
    pattern = r"^(.+?)\s*\|\s*(.+?)\s*\((.+?)\)$"
    match = re.match(pattern, market_hash_name)
    
    if match:
        return match.group(1).strip(), match.group(2).strip(), match.group(3).strip()
    
    # Try without wear
    pattern_no_wear = r"^(.+?)\s*\|\s*(.+?)$"
    match = re.match(pattern_no_wear, market_hash_name)
    
    if match:
        return match.group(1).strip(), match.group(2).strip(), None
    
    return None, None, None


def is_within_price_range(
    price_cny: float,
    config: Config,
) -> bool:
    """
    Check if a price (in CNY) is within the target USD range.
    
    Args:
        price_cny: Price in CNY.
        config: Configuration with price range and FX rate.
        
    Returns:
        True if within range.
    """
    price_usd = price_cny * config.fx_cny_to_usd
    return config.min_price_usd <= price_usd <= config.max_price_usd


def is_allowed_item_type(market_hash_name: str, config: Config) -> bool:
    """
    Check if an item is an allowed type (weapon, knife, gloves).
    
    Args:
        market_hash_name: The item's market hash name.
        config: Configuration with allowed_item_types.
        
    Returns:
        True if item type is allowed.
    """
    if not config.allowed_item_types:
        return True  # No filter, allow all
    
    name_lower = market_hash_name.lower()
    
    # Skip stickers
    if name_lower.startswith("sticker |"):
        return "sticker" in config.allowed_item_types
    
    # Skip graffiti
    if "graffiti |" in name_lower or name_lower.startswith("sealed graffiti"):
        return "graffiti" in config.allowed_item_types
    
    # Skip patches
    if name_lower.startswith("patch |"):
        return "patch" in config.allowed_item_types
    
    # Skip agents
    if any(agent in name_lower for agent in ["agent |", "operator |"]):
        return "agent" in config.allowed_item_types
    
    # Skip music kits
    if name_lower.startswith("music kit |"):
        return "music_kit" in config.allowed_item_types
    
    # Skip cases and keys
    if name_lower.endswith(" case") or name_lower.endswith(" key"):
        return "case" in config.allowed_item_types or "key" in config.allowed_item_types
    
    # Skip capsules, packages, passes
    if any(skip in name_lower for skip in ["capsule", "package", "pass", "pin"]):
        return False
    
    # Knives start with ★
    if name_lower.startswith("★"):
        if "gloves" in name_lower or "hand wraps" in name_lower or "driver gloves" in name_lower or "specialist gloves" in name_lower or "sport gloves" in name_lower or "moto gloves" in name_lower or "hydra gloves" in name_lower or "broken fang gloves" in name_lower:
            return "gloves" in config.allowed_item_types
        return "knife" in config.allowed_item_types
    
    # Regular weapons (have | separator and wear condition)
    if " | " in market_hash_name and "(" in market_hash_name:
        return "weapon" in config.allowed_item_types
    
    # Default: include if we're not sure
    return True


def upsert_buff_item(
    session: Session,
    item_dto: BuffItemDTO,
) -> BuffItem:
    """
    Insert or update a BuffItem.
    
    Args:
        session: Database session.
        item_dto: Item data from API.
        
    Returns:
        The BuffItem instance.
    """
    # Try to find existing item
    existing = session.query(BuffItem).filter(
        BuffItem.goods_id == item_dto.goods_id
    ).first()
    
    if existing:
        # Update last seen time
        existing.last_seen_at = datetime.utcnow()
        return existing
    
    # Parse name components
    weapon, skin_name, wear = parse_item_name(item_dto.market_hash_name)
    
    # Create new item
    item = BuffItem(
        goods_id=item_dto.goods_id,
        market_hash_name=item_dto.market_hash_name,
        weapon=weapon,
        skin_name=skin_name,
        wear=wear,
    )
    session.add(item)
    return item


def create_price_snapshot(
    session: Session,
    item_dto: BuffItemDTO,
    config: Config,
) -> Optional[BuffPriceSnapshot]:
    """
    Create a price snapshot for an item.
    
    Args:
        session: Database session.
        item_dto: Item data from API.
        config: Configuration.
        
    Returns:
        The BuffPriceSnapshot instance, or None if no price data.
    """
    overall_min = item_dto.overall_min_price
    if overall_min is None or overall_min <= 0:
        return None
    
    # Build tag floors JSON
    tag_floors = {}
    for sale in item_dto.sales:
        if sale.tag_name:
            tag_floors[sale.tag_name] = sale.min_price
    
    snapshot = BuffPriceSnapshot(
        goods_id=item_dto.goods_id,
        overall_min_price=overall_min,
        tag_floors_json=json.dumps(tag_floors) if tag_floors else None,
        stat_time=item_dto.stat_time,
        within_target_range=is_within_price_range(overall_min, config),
    )
    session.add(snapshot)
    return snapshot


def ingest_buff_prices_once(
    session: Session,
    config: Optional[Config] = None,
    max_pages: Optional[int] = None,
) -> tuple[int, int]:
    """
    Fetch Buff global floors and store in database.
    
    Args:
        session: Database session.
        config: Optional configuration override.
        max_pages: Optional limit on pages to fetch.
        
    Returns:
        Tuple of (items_processed, snapshots_created).
    """
    config = config or get_config()
    
    logger.info("Starting Buff price ingestion...")
    
    items_processed = 0
    snapshots_created = 0
    
    with BuffClient(config) as client:
        # Fetch all items
        items = client.fetch_all_market_items(max_pages=max_pages)
        
        skipped_type = 0
        for item_dto in items:
            # Skip non-allowed item types
            if not is_allowed_item_type(item_dto.market_hash_name, config):
                skipped_type += 1
                continue
            
            try:
                # Upsert the item
                upsert_buff_item(session, item_dto)
                items_processed += 1
                
                # Create price snapshot
                snapshot = create_price_snapshot(session, item_dto, config)
                if snapshot:
                    snapshots_created += 1
                
                # Commit periodically to avoid large transactions
                if items_processed % 100 == 0:
                    session.commit()
                    logger.debug(f"Processed {items_processed} items...")
                    
            except Exception as e:
                logger.warning(f"Failed to process item {item_dto.goods_id}: {e}")
                continue
    
    # Final commit
    session.commit()
    
    logger.info(
        f"Buff ingestion complete: {items_processed} items processed, "
        f"{snapshots_created} snapshots created, {skipped_type} skipped (wrong type)"
    )
    
    return items_processed, snapshots_created


def get_latest_buff_floor(
    session: Session,
    market_hash_name: str,
) -> Optional[BuffPriceSnapshot]:
    """
    Get the latest Buff floor price for an item.
    
    Args:
        session: Database session.
        market_hash_name: The item's market hash name.
        
    Returns:
        The latest BuffPriceSnapshot, or None if not found.
    """
    # Find the item by name
    item = session.query(BuffItem).filter(
        BuffItem.market_hash_name == market_hash_name
    ).first()
    
    if not item:
        return None
    
    # Get the latest snapshot
    snapshot = session.query(BuffPriceSnapshot).filter(
        BuffPriceSnapshot.goods_id == item.goods_id
    ).order_by(BuffPriceSnapshot.timestamp.desc()).first()
    
    return snapshot


def get_latest_buff_floor_by_goods_id(
    session: Session,
    goods_id: int,
) -> Optional[BuffPriceSnapshot]:
    """
    Get the latest Buff floor price by goods_id.
    
    Args:
        session: Database session.
        goods_id: The Buff goods ID.
        
    Returns:
        The latest BuffPriceSnapshot, or None if not found.
    """
    return session.query(BuffPriceSnapshot).filter(
        BuffPriceSnapshot.goods_id == goods_id
    ).order_by(BuffPriceSnapshot.timestamp.desc()).first()

