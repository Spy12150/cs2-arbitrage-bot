"""
Buff163 Developer API client.

Provides a wrapper around the Buff163 API for fetching market data.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from ..config import Config, get_config
from ..logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class BuffSaleDTO:
    """Data transfer object for a Buff sale/price entry."""
    min_price: float  # In CNY
    tag_id: Optional[int] = None
    tag_name: Optional[str] = None


@dataclass
class BuffItemDTO:
    """Data transfer object for a Buff item."""
    goods_id: int
    market_hash_name: str
    update_time: Optional[int] = None
    stat_time: Optional[int] = None
    sales: list[BuffSaleDTO] = field(default_factory=list)
    
    @property
    def overall_min_price(self) -> Optional[float]:
        """Get the overall minimum price across all sales."""
        if not self.sales:
            return None
        return min(sale.min_price for sale in self.sales)


class BuffClient:
    """
    Client for the Buff163 Developer API.
    
    Handles authentication and provides methods for fetching market data.
    """
    
    def __init__(self, config: Optional[Config] = None):
        """
        Initialize the Buff client.
        
        Args:
            config: Optional configuration override.
        """
        self.config = config or get_config()
        self.base_url = self.config.buff_api_base_url.rstrip("/")
        self._client: Optional[httpx.Client] = None
        self._last_request_time: float = 0
        self._min_request_interval: float = 0.5  # Minimum seconds between requests
    
    @property
    def client(self) -> httpx.Client:
        """Get or create the HTTP client."""
        if self._client is None:
            headers = {
                "User-Agent": "CS2ArbBot/1.0",
                "Accept": "application/json",
            }
            
            # Add API key if configured (Bearer token format per Buff docs)
            if self.config.buff_api_key:
                # Remove quotes if present (common .env mistake)
                api_key = self.config.buff_api_key.strip('"\'')
                headers["Authorization"] = f"Bearer {api_key}"
            
            # Add session cookie if configured (alternative auth)
            cookies = {}
            if self.config.buff_session_cookie:
                cookies["session"] = self.config.buff_session_cookie
            
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                cookies=cookies,
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
            ValueError: On unexpected response format.
        """
        self._rate_limit()
        
        try:
            response = self.client.request(method, endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Buff API typically wraps responses
            if isinstance(data, dict) and "code" in data:
                if data.get("code") != "OK" and data.get("code") != 0:
                    error_msg = data.get("msg", data.get("message", "Unknown error"))
                    logger.error(f"Buff API error: {error_msg}")
                    raise ValueError(f"Buff API error: {error_msg}")
            
            return data
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from Buff API: {e.response.status_code} - {e.response.text}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Request error to Buff API: {e}")
            raise
    
    def fetch_market_items(
        self,
        game: str = "cs2",
        include_sticker: int = 0,
        page_num: int = 1,
        page_size: int = 80,
    ) -> list[BuffItemDTO]:
        """
        Fetch market items with floor prices.
        
        GET /api/market/items?game=cs2&include_sticker=0
        
        Args:
            game: Game identifier ("cs2" or "csgo").
            include_sticker: Whether to include sticker info (0 or 1).
            page_num: Page number for pagination.
            page_size: Items per page.
            
        Returns:
            List of BuffItemDTO with price information.
        """
        params = {
            "game": game,
            "include_sticker": include_sticker,
            "page_num": page_num,
            "page_size": page_size,
        }
        
        logger.debug(f"Fetching Buff market items: page {page_num}")
        
        try:
            data = self._request("GET", "/api/market/items", params=params)
            items = self._parse_market_items(data)
            logger.info(f"Fetched {len(items)} items from Buff (page {page_num})")
            return items
        except Exception as e:
            logger.error(f"Failed to fetch Buff market items: {e}")
            return []
    
    def fetch_all_market_items(
        self,
        game: str = "cs2",
        max_pages: Optional[int] = None,
    ) -> list[BuffItemDTO]:
        """
        Fetch all market items.
        
        Note: The Buff API returns ALL items in a single request,
        so we only need to fetch once (pagination doesn't work as expected).
        
        Args:
            game: Game identifier.
            max_pages: Optional limit on pages to fetch (usually 1 is enough).
            
        Returns:
            List of all BuffItemDTO.
        """
        # Buff API returns all items in one request, no need for pagination
        items = self.fetch_market_items(game=game, page_num=1)
        logger.info(f"Fetched total of {len(items)} items from Buff")
        return items
    
    def _parse_market_items(self, data: dict[str, Any]) -> list[BuffItemDTO]:
        """
        Parse market items response into DTOs.
        
        Args:
            data: Raw API response.
            
        Returns:
            List of BuffItemDTO.
        """
        items: list[BuffItemDTO] = []
        
        # Handle different response formats - Buff uses "info" for the items list
        raw_items = data.get("info", [])
        if not raw_items:
            raw_items = data.get("data", {}).get("items", [])
        if not raw_items:
            raw_items = data.get("items", [])
        
        for raw in raw_items:
            try:
                # Parse sales/prices
                sales: list[BuffSaleDTO] = []
                raw_sales = raw.get("sales", []) or raw.get("sell_min_prices", [])
                
                for sale in raw_sales:
                    if isinstance(sale, dict):
                        sales.append(BuffSaleDTO(
                            min_price=float(sale.get("min_price", 0) or sale.get("price", 0)),
                            tag_id=sale.get("tag_id"),
                            tag_name=sale.get("tag_name"),
                        ))
                    elif isinstance(sale, (int, float)):
                        sales.append(BuffSaleDTO(min_price=float(sale)))
                
                # If no sales data, try to get price directly
                if not sales:
                    min_price = raw.get("sell_min_price") or raw.get("min_price")
                    if min_price:
                        sales.append(BuffSaleDTO(min_price=float(min_price)))
                
                item = BuffItemDTO(
                    goods_id=int(raw.get("goods_id", raw.get("id", 0))),
                    market_hash_name=raw.get("market_hash_name", raw.get("name", "")),
                    update_time=raw.get("update_time"),
                    stat_time=raw.get("stat_time"),
                    sales=sales,
                )
                
                if item.goods_id and item.market_hash_name:
                    items.append(item)
                    
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"Failed to parse Buff item: {e}")
                continue
        
        return items
    
    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
    
    def __enter__(self) -> "BuffClient":
        return self
    
    def __exit__(self, *args) -> None:
        self.close()

