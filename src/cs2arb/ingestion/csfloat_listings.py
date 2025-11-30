"""
CSFloat listings ingestion.

Fetches and stores CSFloat listings into the database.
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from ..clients.csfloat_client import CSFloatClient, CSFloatListingDTO
from ..config import Config, get_config
from ..db.models import CSFloatListing
from ..logging_config import get_logger
from .buff_prices import is_allowed_item_type

logger = get_logger(__name__)


def upsert_csfloat_listing(
    session: Session,
    listing_dto: CSFloatListingDTO,
) -> CSFloatListing:
    """
    Insert or update a CSFloat listing.
    
    Args:
        session: Database session.
        listing_dto: Listing data from API.
        
    Returns:
        The CSFloatListing instance.
    """
    # Serialize stickers to JSON
    stickers_json = None
    if listing_dto.stickers:
        stickers_json = json.dumps([
            {"name": s.name, "slot": s.slot, "wear": s.wear}
            for s in listing_dto.stickers
        ])
    
    # Try to find existing listing
    existing = session.query(CSFloatListing).filter(
        CSFloatListing.csfloat_id == listing_dto.listing_id
    ).first()
    
    if existing:
        # Update existing listing
        existing.price_cents = listing_dto.price_cents
        existing.discount = listing_dto.discount
        existing.last_checked_at = datetime.utcnow()
        existing.is_active = True
        existing.reference_quantity = listing_dto.reference_quantity
        existing.watchers = listing_dto.watchers
        if stickers_json:
            existing.stickers_json = stickers_json
        session.flush()  # Flush to ensure changes are written
        return existing
    
    # Create new listing
    listing = CSFloatListing(
        csfloat_id=listing_dto.listing_id,
        market_hash_name=listing_dto.market_hash_name,
        price_cents=listing_dto.price_cents,
        discount=listing_dto.discount,
        listing_type=listing_dto.listing_type,
        float_value=listing_dto.float_value,
        paint_seed=listing_dto.paint_seed,
        wear_name=listing_dto.wear_name,
        stickers_json=stickers_json,
        reference_quantity=listing_dto.reference_quantity,
        watchers=listing_dto.watchers,
    )
    session.add(listing)
    session.flush()  # Flush to catch duplicates immediately
    return listing


def ingest_csfloat_listings_once(
    session: Session,
    config: Optional[Config] = None,
) -> list[CSFloatListing]:
    """
    Fetch CSFloat buy-now listings and store in database.
    
    Args:
        session: Database session.
        config: Optional configuration override.
        
    Returns:
        List of CSFloatListing instances that were processed.
    """
    config = config or get_config()
    
    logger.info("Starting CSFloat listings ingestion...")
    
    # Convert USD to cents
    min_price_cents = int(config.min_price_usd * 100)
    max_price_cents = int(config.max_price_usd * 100)
    
    processed_listings: list[CSFloatListing] = []
    
    with CSFloatClient(config) as client:
        # Fetch top discounted listings (don't filter by min_discount here,
        # we want to store all listings and filter during signal computation)
        listings = client.fetch_top_discounted_buy_now_listings(
            min_price_cents=min_price_cents,
            max_price_cents=max_price_cents,
            pages=config.csfloat_pages_to_fetch,
            min_discount=None,  # Don't filter - store all, analyze later
        )
        
        # Track processed IDs to avoid duplicates within this batch
        processed_ids: set[str] = set()
        skipped_type = 0
        
        for listing_dto in listings:
            # Skip if already processed in this batch
            if listing_dto.listing_id in processed_ids:
                continue
            processed_ids.add(listing_dto.listing_id)
            
            # Skip non-allowed item types
            if not is_allowed_item_type(listing_dto.market_hash_name, config):
                skipped_type += 1
                continue
            
            try:
                listing = upsert_csfloat_listing(session, listing_dto)
                processed_listings.append(listing)
            except Exception as e:
                logger.warning(f"Failed to process listing {listing_dto.listing_id}: {e}")
                session.rollback()  # Rollback to recover from error
                continue
        
        if skipped_type > 0:
            logger.info(f"Skipped {skipped_type} non-weapon items (stickers, etc.)")
    
    # Commit changes
    session.commit()
    
    logger.info(f"CSFloat ingestion complete: {len(processed_listings)} listings processed")
    
    return processed_listings


def mark_inactive_listings(
    session: Session,
    active_listing_ids: set[str],
) -> int:
    """
    Mark listings not in the active set as inactive.
    
    Args:
        session: Database session.
        active_listing_ids: Set of currently active listing IDs.
        
    Returns:
        Number of listings marked inactive.
    """
    # Find listings that were active but are no longer in the set
    listings = session.query(CSFloatListing).filter(
        CSFloatListing.is_active == True,
        ~CSFloatListing.csfloat_id.in_(active_listing_ids),
    ).all()
    
    for listing in listings:
        listing.is_active = False
    
    session.commit()
    
    logger.info(f"Marked {len(listings)} listings as inactive")
    return len(listings)


def get_active_listings_for_item(
    session: Session,
    market_hash_name: str,
) -> list[CSFloatListing]:
    """
    Get active CSFloat listings for a specific item.
    
    Args:
        session: Database session.
        market_hash_name: The item's market hash name.
        
    Returns:
        List of active listings.
    """
    return session.query(CSFloatListing).filter(
        CSFloatListing.market_hash_name == market_hash_name,
        CSFloatListing.is_active == True,
    ).order_by(CSFloatListing.price_cents.asc()).all()


def get_lowest_csfloat_price(
    session: Session,
    market_hash_name: str,
) -> Optional[int]:
    """
    Get the lowest CSFloat price for an item.
    
    Args:
        session: Database session.
        market_hash_name: The item's market hash name.
        
    Returns:
        Lowest price in cents, or None if no listings.
    """
    listing = session.query(CSFloatListing).filter(
        CSFloatListing.market_hash_name == market_hash_name,
        CSFloatListing.is_active == True,
    ).order_by(CSFloatListing.price_cents.asc()).first()
    
    return listing.price_cents if listing else None

