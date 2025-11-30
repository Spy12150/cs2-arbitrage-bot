"""
CSFloat API client.

Provides a wrapper around the CSFloat API for fetching market listings.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from ..config import Config, get_config
from ..logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CSFloatStickerDTO:
    """Data transfer object for a sticker on an item."""
    name: str
    slot: int
    wear: Optional[float] = None


@dataclass
class CSFloatListingDTO:
    """Data transfer object for a CSFloat listing."""
    listing_id: str
    market_hash_name: str
    price_cents: int  # Price in cents (USD)
    discount: Optional[float] = None  # e.g., 0.15 for 15% discount
    listing_type: str = "buy_now"
    float_value: Optional[float] = None
    paint_seed: Optional[int] = None
    wear_name: Optional[str] = None
    stickers: list[CSFloatStickerDTO] = field(default_factory=list)
    created_at: Optional[str] = None
    # Volume/liquidity indicators
    reference_quantity: Optional[int] = None  # Number of listings for this item
    watchers: Optional[int] = None  # Number of people watching this listing
    
    @property
    def price_usd(self) -> float:
        """Get price in USD."""
        return self.price_cents / 100.0


class CSFloatClient:
    """
    Client for the CSFloat API.
    
    Handles authentication and provides methods for fetching listings.
    """
    
    def __init__(self, config: Optional[Config] = None):
        """
        Initialize the CSFloat client.
        
        Args:
            config: Optional configuration override.
        """
        self.config = config or get_config()
        self.base_url = self.config.csfloat_api_base_url.rstrip("/")
        self._client: Optional[httpx.Client] = None
        self._last_request_time: float = 0
        self._min_request_interval: float = 0.3  # Minimum seconds between requests
    
    @property
    def client(self) -> httpx.Client:
        """Get or create the HTTP client."""
        if self._client is None:
            headers = {
                "User-Agent": "CS2ArbBot/1.0",
                "Accept": "application/json",
            }
            
            # Add API key if configured
            if self.config.csfloat_api_key:
                # Remove quotes if present (common .env mistake)
                api_key = self.config.csfloat_api_key.strip('"\'')
                headers["Authorization"] = api_key
            
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=30.0,
            )
        return self._client
    
    def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Make an API request with error handling.
        
        Args:
            method: HTTP method.
            endpoint: API endpoint path.
            params: Optional query parameters.
            
        Returns:
            Parsed JSON response.
            
        Raises:
            httpx.HTTPError: On HTTP errors.
        """
        self._rate_limit()
        
        try:
            response = self.client.request(method, endpoint, params=params)
            response.raise_for_status()
            return response.json()
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from CSFloat API: {e.response.status_code}")
            # Try to parse error message
            try:
                error_data = e.response.json()
                logger.error(f"CSFloat error: {error_data}")
            except Exception:
                logger.error(f"Response text: {e.response.text[:500]}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error to CSFloat API: {e}")
            raise
    
    def fetch_listings(
        self,
        listing_type: str = "buy_now",
        min_price_cents: Optional[int] = None,
        max_price_cents: Optional[int] = None,
        sort_by: str = "highest_discount",
        limit: int = 50,
        cursor: Optional[str] = None,
        market_hash_name: Optional[str] = None,
    ) -> tuple[list[CSFloatListingDTO], Optional[str]]:
        """
        Fetch listings from CSFloat.
        
        GET /api/v1/listings
        
        Args:
            listing_type: Type of listing (buy_now, auction).
            min_price_cents: Minimum price in cents.
            max_price_cents: Maximum price in cents.
            sort_by: Sort order (highest_discount, lowest_price, etc.).
            limit: Number of results per page (max 50).
            cursor: Pagination cursor.
            market_hash_name: Filter by specific item.
            
        Returns:
            Tuple of (list of listings, next cursor for pagination).
        """
        params: dict[str, Any] = {
            "type": listing_type,
            "sort_by": sort_by,
            "limit": min(limit, 50),
        }
        
        if min_price_cents is not None:
            params["min_price"] = min_price_cents
        if max_price_cents is not None:
            params["max_price"] = max_price_cents
        if cursor:
            params["cursor"] = cursor
        if market_hash_name:
            params["market_hash_name"] = market_hash_name
        
        logger.debug(f"Fetching CSFloat listings: {params}")
        
        try:
            data = self._request("GET", "/api/v1/listings", params=params)
            listings = self._parse_listings(data)
            next_cursor = data.get("cursor")
            
            logger.info(f"Fetched {len(listings)} listings from CSFloat")
            return listings, next_cursor
            
        except Exception as e:
            logger.error(f"Failed to fetch CSFloat listings: {e}")
            return [], None
    
    def fetch_top_discounted_buy_now_listings(
        self,
        min_price_cents: int,
        max_price_cents: Optional[int] = None,
        pages: int = 3,
        min_discount: Optional[float] = None,
    ) -> list[CSFloatListingDTO]:
        """
        Fetch top discounted buy-now listings.
        
        Args:
            min_price_cents: Minimum price in cents.
            max_price_cents: Optional maximum price in cents.
            pages: Number of pages to fetch.
            min_discount: Optional minimum discount threshold.
            
        Returns:
            List of CSFloatListingDTO sorted by discount.
        """
        all_listings: list[CSFloatListingDTO] = []
        cursor: Optional[str] = None
        
        for page in range(pages):
            listings, cursor = self.fetch_listings(
                listing_type="buy_now",
                min_price_cents=min_price_cents,
                max_price_cents=max_price_cents,
                sort_by="highest_discount",
                cursor=cursor,
            )
            
            if not listings:
                break
            
            all_listings.extend(listings)
            
            if cursor is None:
                break
        
        # Apply minimum discount filter if specified
        if min_discount is not None:
            all_listings = [
                l for l in all_listings
                if l.discount is not None and l.discount >= min_discount
            ]
        
        logger.info(f"Fetched total of {len(all_listings)} discounted listings")
        return all_listings
    
    def fetch_lowest_price_listing(
        self,
        market_hash_name: str,
    ) -> Optional[CSFloatListingDTO]:
        """
        Fetch the lowest priced listing for a specific item.
        
        Args:
            market_hash_name: The item's market hash name.
            
        Returns:
            The lowest priced listing, or None if not found.
        """
        listings, _ = self.fetch_listings(
            listing_type="buy_now",
            sort_by="lowest_price",
            limit=1,
            market_hash_name=market_hash_name,
        )
        return listings[0] if listings else None
    
    def _parse_listings(self, data: dict[str, Any]) -> list[CSFloatListingDTO]:
        """
        Parse listings response into DTOs.
        
        Args:
            data: Raw API response.
            
        Returns:
            List of CSFloatListingDTO.
        """
        listings: list[CSFloatListingDTO] = []
        
        raw_listings = data.get("data", [])
        if not raw_listings:
            raw_listings = data.get("listings", [])
        
        for raw in raw_listings:
            try:
                # Parse item details
                item = raw.get("item", {})
                
                # Parse stickers
                stickers: list[CSFloatStickerDTO] = []
                for sticker in item.get("stickers", []) or []:
                    if sticker:
                        stickers.append(CSFloatStickerDTO(
                            name=sticker.get("name", ""),
                            slot=sticker.get("slot", 0),
                            wear=sticker.get("wear"),
                        ))
                
                # Determine wear name from float
                float_value = item.get("float_value")
                wear_name = item.get("wear_name")
                if not wear_name and float_value is not None:
                    wear_name = self._float_to_wear(float_value)
                
                # Get reference/volume data
                reference = raw.get("reference", {})
                reference_quantity = reference.get("quantity") if reference else None
                watchers = raw.get("watchers")
                
                listing = CSFloatListingDTO(
                    listing_id=str(raw.get("id", "")),
                    market_hash_name=item.get("market_hash_name", ""),
                    price_cents=int(raw.get("price", 0)),
                    discount=raw.get("discount"),  # May be None
                    listing_type=raw.get("type", "buy_now"),
                    float_value=float_value,
                    paint_seed=item.get("paint_seed"),
                    wear_name=wear_name,
                    stickers=stickers,
                    created_at=raw.get("created_at"),
                    reference_quantity=reference_quantity,
                    watchers=watchers,
                )
                
                if listing.listing_id and listing.market_hash_name and listing.price_cents > 0:
                    listings.append(listing)
                    
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"Failed to parse CSFloat listing: {e}")
                continue
        
        return listings
    
    @staticmethod
    def _float_to_wear(float_value: float) -> str:
        """Convert float value to wear name."""
        if float_value < 0.07:
            return "Factory New"
        elif float_value < 0.15:
            return "Minimal Wear"
        elif float_value < 0.38:
            return "Field-Tested"
        elif float_value < 0.45:
            return "Well-Worn"
        else:
            return "Battle-Scarred"
    
    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
    
    def __enter__(self) -> "CSFloatClient":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()

