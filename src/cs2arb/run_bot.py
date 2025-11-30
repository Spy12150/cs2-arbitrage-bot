"""
Main bot runner for CS2 Arbitrage Bot.

Runs continuous scanning loops for Buff prices and CSFloat listings.
"""

import signal
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

from .config import get_config
from .core.arbitrage_engine import (
    compute_buff_to_csfloat_signals,
    compute_csfloat_to_buff_signals,
    deactivate_stale_signals,
)
from .core.watchlist import get_default_watchlist
from .db import get_session, init_engine
from .db.init_db import create_database
from .ingestion import ingest_buff_prices_once, ingest_csfloat_listings_once
from .logging_config import get_logger, setup_logging

logger = get_logger(__name__)


class ArbBot:
    """
    Arbitrage bot that continuously scans markets for opportunities.
    
    Runs two main loops:
    - Buff price ingestion (every ~10 minutes)
    - CSFloat listing ingestion + signal computation (every ~30 seconds)
    """
    
    def __init__(self):
        self.config = get_config()
        self.running = False
        self._last_buff_scan: Optional[datetime] = None
        self._last_csfloat_scan: Optional[datetime] = None
        self._last_buff_to_csfloat_scan: Optional[datetime] = None
        self._last_stale_cleanup: Optional[datetime] = None
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Shutdown signal received. Stopping bot...")
        self.running = False
    
    def should_scan_buff(self) -> bool:
        """Check if it's time to scan Buff prices."""
        if self._last_buff_scan is None:
            return True
        
        elapsed = (datetime.now() - self._last_buff_scan).total_seconds()
        return elapsed >= self.config.buff_scan_interval_seconds
    
    def should_scan_csfloat(self) -> bool:
        """Check if it's time to scan CSFloat listings."""
        if self._last_csfloat_scan is None:
            return True
        
        elapsed = (datetime.now() - self._last_csfloat_scan).total_seconds()
        return elapsed >= self.config.csfloat_scan_interval_seconds
    
    def should_scan_buff_to_csfloat(self) -> bool:
        """Check if it's time to scan Buff → CSFloat opportunities."""
        if self._last_buff_to_csfloat_scan is None:
            return True
        
        # Run every 30 minutes
        elapsed = (datetime.now() - self._last_buff_to_csfloat_scan).total_seconds()
        return elapsed >= 1800
    
    def should_cleanup_stale(self) -> bool:
        """Check if it's time to cleanup stale signals."""
        if self._last_stale_cleanup is None:
            return True
        
        # Run every hour
        elapsed = (datetime.now() - self._last_stale_cleanup).total_seconds()
        return elapsed >= 3600
    
    def run_buff_scan(self) -> None:
        """Run Buff price ingestion."""
        logger.info("Starting Buff price scan...")
        
        try:
            with get_session() as session:
                items, snapshots = ingest_buff_prices_once(session, self.config)
                logger.info(f"Buff scan complete: {items} items, {snapshots} snapshots")
            
            self._last_buff_scan = datetime.now()
            
        except Exception as e:
            logger.error(f"Buff scan failed: {e}")
    
    def run_csfloat_scan(self) -> None:
        """Run CSFloat listings ingestion and signal computation."""
        logger.info("Starting CSFloat listings scan...")
        
        try:
            with get_session() as session:
                # Fetch new listings
                listings = ingest_csfloat_listings_once(session, self.config)
                logger.info(f"CSFloat scan complete: {len(listings)} listings")
                
                # Compute signals for new listings
                if listings:
                    signals = compute_csfloat_to_buff_signals(session, self.config, listings)
                    logger.info(f"Computed {len(signals)} CSFloat→Buff signals")
            
            self._last_csfloat_scan = datetime.now()
            
        except Exception as e:
            logger.error(f"CSFloat scan failed: {e}")
    
    def run_buff_to_csfloat_scan(self) -> None:
        """Run Buff → CSFloat signal computation for watchlist items."""
        logger.info("Starting Buff → CSFloat scan...")
        
        try:
            watchlist = get_default_watchlist()
            
            with get_session() as session:
                signals = compute_buff_to_csfloat_signals(session, self.config, watchlist)
                logger.info(f"Computed {len(signals)} Buff→CSFloat signals")
            
            self._last_buff_to_csfloat_scan = datetime.now()
            
        except Exception as e:
            logger.error(f"Buff→CSFloat scan failed: {e}")
    
    def run_stale_cleanup(self) -> None:
        """Clean up stale signals."""
        logger.info("Cleaning up stale signals...")
        
        try:
            with get_session() as session:
                count = deactivate_stale_signals(session, max_age_hours=24)
                logger.info(f"Deactivated {count} stale signals")
            
            self._last_stale_cleanup = datetime.now()
            
        except Exception as e:
            logger.error(f"Stale cleanup failed: {e}")
    
    def run(self) -> None:
        """Run the main bot loop."""
        logger.info("=" * 60)
        logger.info("CS2 Arbitrage Bot starting...")
        logger.info("=" * 60)
        logger.info(f"Configuration:")
        logger.info(f"  Buff scan interval: {self.config.buff_scan_interval_seconds}s")
        logger.info(f"  CSFloat scan interval: {self.config.csfloat_scan_interval_seconds}s")
        logger.info(f"  Price range: ${self.config.min_price_usd}–${self.config.max_price_usd}")
        logger.info(f"  Min ROI (CF→Buff): {self.config.min_roi_csfloat_to_buff:.0%}")
        logger.info(f"  FX rate: ¥1 = ${self.config.fx_cny_to_usd}")
        logger.info("=" * 60)
        
        # Ensure database exists
        create_database()
        init_engine()
        
        self.running = True
        
        # Run initial scans
        logger.info("Running initial scans...")
        self.run_buff_scan()
        self.run_csfloat_scan()
        
        # Main loop
        logger.info("Entering main loop. Press Ctrl+C to stop.")
        
        while self.running:
            try:
                # Check what needs to run
                if self.should_scan_buff():
                    self.run_buff_scan()
                
                if self.should_scan_csfloat():
                    self.run_csfloat_scan()
                
                if self.should_scan_buff_to_csfloat():
                    self.run_buff_to_csfloat_scan()
                
                if self.should_cleanup_stale():
                    self.run_stale_cleanup()
                
                # Sleep a bit before checking again
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received.")
                self.running = False
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(10)  # Wait a bit before retrying
        
        logger.info("Bot stopped.")


def main():
    """Entry point for the bot."""
    setup_logging()
    bot = ArbBot()
    bot.run()


if __name__ == "__main__":
    main()

