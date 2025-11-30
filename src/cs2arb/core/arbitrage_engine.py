"""
Arbitrage engine for CS2 skins.

Computes arbitrage opportunities between Buff163 and CSFloat.
"""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from ..clients.csfloat_client import CSFloatClient
from ..config import Config, get_config
from ..db.models import ArbitrageSignal, BuffItem, BuffPriceSnapshot, CSFloatListing
from ..logging_config import get_logger
from .watchlist import Watchlist, get_default_watchlist

logger = get_logger(__name__)


def compute_csfloat_to_buff_signals(
    session: Session,
    config: Optional[Config] = None,
    listings: Optional[list[CSFloatListing]] = None,
) -> list[ArbitrageSignal]:
    """
    Compute CSFloat → Buff arbitrage signals.
    
    For each CSFloat listing, checks if buying on CSFloat and selling on Buff
    would yield a profit above the minimum ROI threshold.
    
    Args:
        session: Database session.
        config: Optional configuration override.
        listings: Optional list of listings to process. If None, queries active listings.
        
    Returns:
        List of ArbitrageSignal instances created.
    """
    config = config or get_config()
    
    logger.info("Computing CSFloat → Buff arbitrage signals...")
    logger.info(f"  Filters: min_listings={config.min_csfloat_listings}, min_roi={config.min_roi_csfloat_to_buff:.0%}")
    
    # Get listings to process
    if listings is None:
        listings = session.query(CSFloatListing).filter(
            CSFloatListing.is_active == True,
        ).all()
    
    signals_created: list[ArbitrageSignal] = []
    skipped_low_volume = 0
    
    for listing in listings:
        # Filter by volume/liquidity
        if listing.reference_quantity is not None:
            if listing.reference_quantity < config.min_csfloat_listings:
                skipped_low_volume += 1
                continue
        
        if listing.watchers is not None:
            if listing.watchers < config.min_watchers:
                continue
        
        try:
            signal = _compute_signal_for_listing(session, listing, config)
            if signal:
                signals_created.append(signal)
        except Exception as e:
            logger.warning(f"Error computing signal for listing {listing.csfloat_id}: {e}")
            continue
    
    # Commit new signals
    session.commit()
    
    if skipped_low_volume > 0:
        logger.info(f"Skipped {skipped_low_volume} low-volume items (< {config.min_csfloat_listings} listings)")
    logger.info(f"Created {len(signals_created)} CSFloat → Buff signals")
    return signals_created


def _compute_signal_for_listing(
    session: Session,
    listing: CSFloatListing,
    config: Config,
) -> Optional[ArbitrageSignal]:
    """
    Compute arbitrage signal for a single CSFloat listing.
    
    Args:
        session: Database session.
        listing: The CSFloat listing to analyze.
        config: Configuration.
        
    Returns:
        ArbitrageSignal if profitable, None otherwise.
    """
    # Find corresponding Buff item
    buff_item = session.query(BuffItem).filter(
        BuffItem.market_hash_name == listing.market_hash_name
    ).first()
    
    if not buff_item:
        logger.debug(f"No Buff item found for: {listing.market_hash_name}")
        return None
    
    # Get latest Buff floor price
    buff_snapshot = session.query(BuffPriceSnapshot).filter(
        BuffPriceSnapshot.goods_id == buff_item.goods_id
    ).order_by(BuffPriceSnapshot.timestamp.desc()).first()
    
    if not buff_snapshot:
        logger.debug(f"No Buff price snapshot for: {listing.market_hash_name}")
        return None
    
    # Check if snapshot is recent enough (within last 24 hours)
    if buff_snapshot.timestamp < datetime.utcnow() - timedelta(hours=24):
        logger.debug(f"Buff snapshot too old for: {listing.market_hash_name}")
        return None
    
    # Convert prices
    csfloat_price_usd = listing.price_cents / 100.0
    buff_floor_cny = buff_snapshot.overall_min_price
    buff_floor_usd = buff_floor_cny * config.fx_cny_to_usd
    
    # Apply fees
    # CSFloat: buyer pays the listed price (no additional fee typically)
    net_buy_cost = csfloat_price_usd * (1 + config.csfloat_buy_fee_pct)
    
    # Buff: seller pays a fee when selling
    net_sell_proceeds = buff_floor_usd * (1 - config.buff_sell_fee_pct)
    
    # Compute ROI
    if net_buy_cost <= 0:
        return None
    
    roi_pct = (net_sell_proceeds - net_buy_cost) / net_buy_cost
    
    # Check if meets threshold
    if roi_pct < config.min_roi_csfloat_to_buff:
        return None
    
    # Check for existing active signal for this listing
    existing = session.query(ArbitrageSignal).filter(
        ArbitrageSignal.csfloat_listing_id == listing.id,
        ArbitrageSignal.direction == "CSFLOAT_TO_BUFF",
        ArbitrageSignal.is_active == True,
    ).first()
    
    if existing:
        # Update existing signal
        existing.buff_floor_cny = buff_floor_cny
        existing.buff_floor_usd = buff_floor_usd
        existing.csfloat_price_usd = csfloat_price_usd
        existing.roi_pct = roi_pct
        logger.debug(f"Updated signal for {listing.market_hash_name}: ROI {roi_pct:.1%}")
        return existing
    
    # Create new signal
    signal = ArbitrageSignal(
        direction="CSFLOAT_TO_BUFF",
        market_hash_name=listing.market_hash_name,
        buff_goods_id=buff_item.goods_id,
        csfloat_listing_id=listing.id,
        buff_floor_cny=buff_floor_cny,
        buff_floor_usd=buff_floor_usd,
        csfloat_price_usd=csfloat_price_usd,
        roi_pct=roi_pct,
    )
    session.add(signal)
    
    logger.info(
        f"New signal: {listing.market_hash_name} | "
        f"Buy ${csfloat_price_usd:.2f} → Sell ${buff_floor_usd:.2f} | "
        f"ROI: {roi_pct:.1%}"
    )
    
    return signal


def compute_buff_to_csfloat_signals(
    session: Session,
    config: Optional[Config] = None,
    watchlist: Optional[Watchlist] = None,
) -> list[ArbitrageSignal]:
    """
    Compute Buff → CSFloat arbitrage signals for watchlisted items.
    
    For each item in the watchlist, checks if buying on Buff and selling on CSFloat
    would yield a profit above the minimum ROI threshold.
    
    Note: This is a simplified implementation that only checks watchlisted items
    to respect rate limits.
    
    Args:
        session: Database session.
        config: Optional configuration override.
        watchlist: Optional watchlist. If None, uses default watchlist.
        
    Returns:
        List of ArbitrageSignal instances created.
    """
    config = config or get_config()
    watchlist = watchlist or get_default_watchlist()
    
    logger.info("Computing Buff → CSFloat arbitrage signals...")
    
    signals_created: list[ArbitrageSignal] = []
    
    # Use CSFloat client to check current prices
    with CSFloatClient(config) as csfloat_client:
        for item_name in watchlist.items:
            try:
                signal = _compute_buff_to_csfloat_signal(
                    session, item_name, config, csfloat_client
                )
                if signal:
                    signals_created.append(signal)
            except Exception as e:
                logger.warning(f"Error computing Buff→CSFloat signal for {item_name}: {e}")
                continue
    
    session.commit()
    
    logger.info(f"Created {len(signals_created)} Buff → CSFloat signals")
    return signals_created


def _compute_buff_to_csfloat_signal(
    session: Session,
    market_hash_name: str,
    config: Config,
    csfloat_client: CSFloatClient,
) -> Optional[ArbitrageSignal]:
    """
    Compute Buff → CSFloat signal for a single item.
    
    Args:
        session: Database session.
        market_hash_name: Item to check.
        config: Configuration.
        csfloat_client: CSFloat API client.
        
    Returns:
        ArbitrageSignal if profitable, None otherwise.
    """
    # Get Buff floor
    buff_item = session.query(BuffItem).filter(
        BuffItem.market_hash_name == market_hash_name
    ).first()
    
    if not buff_item:
        logger.debug(f"No Buff item found for: {market_hash_name}")
        return None
    
    buff_snapshot = session.query(BuffPriceSnapshot).filter(
        BuffPriceSnapshot.goods_id == buff_item.goods_id
    ).order_by(BuffPriceSnapshot.timestamp.desc()).first()
    
    if not buff_snapshot:
        logger.debug(f"No Buff price snapshot for: {market_hash_name}")
        return None
    
    # Get CSFloat floor (fetch fresh from API)
    csfloat_listing = csfloat_client.fetch_lowest_price_listing(market_hash_name)
    
    if not csfloat_listing:
        logger.debug(f"No CSFloat listing found for: {market_hash_name}")
        return None
    
    # Convert prices
    buff_floor_cny = buff_snapshot.overall_min_price
    buff_floor_usd = buff_floor_cny * config.fx_cny_to_usd
    csfloat_floor_usd = csfloat_listing.price_cents / 100.0
    
    # Apply fees
    # Buff: buyer pays the listed price (may have small fee depending on payment method)
    net_buy_cost = buff_floor_usd * (1 + config.buff_sell_fee_pct)  # Approximate
    
    # CSFloat: seller pays a fee when selling
    net_sell_proceeds = csfloat_floor_usd * (1 - config.csfloat_sell_fee_pct)
    
    # Compute ROI
    if net_buy_cost <= 0:
        return None
    
    roi_pct = (net_sell_proceeds - net_buy_cost) / net_buy_cost
    
    # Check if meets threshold
    if roi_pct < config.min_roi_buff_to_csfloat:
        return None
    
    # Check for existing active signal
    existing = session.query(ArbitrageSignal).filter(
        ArbitrageSignal.market_hash_name == market_hash_name,
        ArbitrageSignal.direction == "BUFF_TO_CSFLOAT",
        ArbitrageSignal.is_active == True,
    ).first()
    
    if existing:
        # Update existing signal
        existing.buff_floor_cny = buff_floor_cny
        existing.buff_floor_usd = buff_floor_usd
        existing.csfloat_price_usd = csfloat_floor_usd
        existing.roi_pct = roi_pct
        return existing
    
    # Create new signal
    signal = ArbitrageSignal(
        direction="BUFF_TO_CSFLOAT",
        market_hash_name=market_hash_name,
        buff_goods_id=buff_item.goods_id,
        csfloat_listing_id=None,  # No specific listing, just floor price
        buff_floor_cny=buff_floor_cny,
        buff_floor_usd=buff_floor_usd,
        csfloat_price_usd=csfloat_floor_usd,
        roi_pct=roi_pct,
    )
    session.add(signal)
    
    logger.info(
        f"New Buff→CSFloat signal: {market_hash_name} | "
        f"Buy ${buff_floor_usd:.2f} → Sell ${csfloat_floor_usd:.2f} | "
        f"ROI: {roi_pct:.1%}"
    )
    
    return signal


def deactivate_stale_signals(
    session: Session,
    max_age_hours: int = 24,
) -> int:
    """
    Deactivate signals older than the specified age.
    
    Args:
        session: Database session.
        max_age_hours: Maximum age in hours.
        
    Returns:
        Number of signals deactivated.
    """
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    
    stale_signals = session.query(ArbitrageSignal).filter(
        ArbitrageSignal.is_active == True,
        ArbitrageSignal.created_at < cutoff,
    ).all()
    
    for signal in stale_signals:
        signal.is_active = False
    
    session.commit()
    
    logger.info(f"Deactivated {len(stale_signals)} stale signals")
    return len(stale_signals)


def get_top_signals(
    session: Session,
    direction: Optional[str] = None,
    min_roi: Optional[float] = None,
    limit: int = 20,
    active_only: bool = True,
) -> list[ArbitrageSignal]:
    """
    Get top arbitrage signals sorted by ROI.
    
    Args:
        session: Database session.
        direction: Optional filter by direction.
        min_roi: Optional minimum ROI threshold.
        limit: Maximum number of signals to return.
        active_only: Only return active signals.
        
    Returns:
        List of ArbitrageSignal sorted by ROI descending.
    """
    query = session.query(ArbitrageSignal)
    
    if active_only:
        query = query.filter(ArbitrageSignal.is_active == True)
    
    if direction:
        query = query.filter(ArbitrageSignal.direction == direction)
    
    if min_roi is not None:
        query = query.filter(ArbitrageSignal.roi_pct >= min_roi)
    
    return query.order_by(ArbitrageSignal.roi_pct.desc()).limit(limit).all()

