"""
DexScreener API Client for MegaETH Chain
Fetches token pairs, prices, and trading data from https://dexscreener.com/megaeth/
"""
import aiohttp
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import logging

from config import config

logger = logging.getLogger(__name__)


@dataclass
class TokenPair:
    """Represents a trading pair on MegaETH"""
    chain_id: str
    dex_id: str
    pair_address: str
    base_token_address: str
    base_token_name: str
    base_token_symbol: str
    quote_token_address: str
    quote_token_name: str
    quote_token_symbol: str
    price_native: str
    price_usd: Optional[str]
    volume_24h: Optional[float]
    liquidity_usd: Optional[float]
    fdv: Optional[float]
    market_cap: Optional[float]
    price_change_5m: Optional[float]
    price_change_1h: Optional[float]
    price_change_6h: Optional[float]
    price_change_24h: Optional[float]
    txns_24h_buys: int
    txns_24h_sells: int
    pair_created_at: Optional[datetime]
    url: str
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "TokenPair":
        """Parse API response into TokenPair object"""
        price_change = data.get("priceChange", {})
        txns = data.get("txns", {}).get("h24", {})
        liquidity = data.get("liquidity", {})
        volume = data.get("volume", {})
        
        pair_created_at = None
        if data.get("pairCreatedAt"):
            try:
                pair_created_at = datetime.fromtimestamp(data["pairCreatedAt"] / 1000)
            except (ValueError, TypeError):
                pass
        
        return cls(
            chain_id=data.get("chainId", ""),
            dex_id=data.get("dexId", ""),
            pair_address=data.get("pairAddress", ""),
            base_token_address=data.get("baseToken", {}).get("address", ""),
            base_token_name=data.get("baseToken", {}).get("name", ""),
            base_token_symbol=data.get("baseToken", {}).get("symbol", ""),
            quote_token_address=data.get("quoteToken", {}).get("address", ""),
            quote_token_name=data.get("quoteToken", {}).get("name", ""),
            quote_token_symbol=data.get("quoteToken", {}).get("symbol", ""),
            price_native=data.get("priceNative", "0"),
            price_usd=data.get("priceUsd"),
            volume_24h=volume.get("h24"),
            liquidity_usd=liquidity.get("usd"),
            fdv=data.get("fdv"),
            market_cap=data.get("marketCap"),
            price_change_5m=price_change.get("m5"),
            price_change_1h=price_change.get("h1"),
            price_change_6h=price_change.get("h6"),
            price_change_24h=price_change.get("h24"),
            txns_24h_buys=txns.get("buys", 0),
            txns_24h_sells=txns.get("sells", 0),
            pair_created_at=pair_created_at,
            url=data.get("url", f"https://dexscreener.com/{data.get('chainId')}/{data.get('pairAddress')}")
        )
    
    def get_age_minutes(self) -> Optional[float]:
        """Get the age of the pair in minutes"""
        if self.pair_created_at:
            delta = datetime.now() - self.pair_created_at
            return delta.total_seconds() / 60
        return None
    
    def format_price(self) -> str:
        """Format price for display"""
        if self.price_usd:
            try:
                price = float(self.price_usd)
                if price < 0.0001:
                    return f"${price:.8f}"
                elif price < 1:
                    return f"${price:.6f}"
                else:
                    return f"${price:.4f}"
            except ValueError:
                return self.price_usd
        return "N/A"
    
    def format_volume(self) -> str:
        """Format volume for display"""
        if self.volume_24h:
            if self.volume_24h >= 1_000_000:
                return f"${self.volume_24h / 1_000_000:.2f}M"
            elif self.volume_24h >= 1_000:
                return f"${self.volume_24h / 1_000:.2f}K"
            else:
                return f"${self.volume_24h:.2f}"
        return "N/A"
    
    def format_liquidity(self) -> str:
        """Format liquidity for display"""
        if self.liquidity_usd:
            if self.liquidity_usd >= 1_000_000:
                return f"${self.liquidity_usd / 1_000_000:.2f}M"
            elif self.liquidity_usd >= 1_000:
                return f"${self.liquidity_usd / 1_000:.2f}K"
            else:
                return f"${self.liquidity_usd:.2f}"
        return "N/A"
    
    def format_market_cap(self) -> str:
        """Format market cap for display"""
        mc = self.market_cap or self.fdv
        if mc:
            if mc >= 1_000_000:
                return f"${mc / 1_000_000:.2f}M"
            elif mc >= 1_000:
                return f"${mc / 1_000:.2f}K"
            else:
                return f"${mc:.2f}"
        return "N/A"


class DexScreenerClient:
    """Client for interacting with DexScreener API"""
    
    def __init__(self):
        self.base_url = config.DEXSCREENER_BASE_URL
        self.chain_id = config.MEGAETH_CHAIN_ID
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                headers={"Accept": "application/json"},
                timeout=timeout
            )
        return self._session
    
    async def close(self):
        """Close the aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Make HTTP request to DexScreener API"""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"DexScreener API error: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"HTTP request failed: {e}")
            return None
    
    async def search_pairs(self, query: str) -> List[TokenPair]:
        """Search for pairs matching a query"""
        data = await self._make_request("/latest/dex/search", {"q": query})
        if data and "pairs" in data:
            pairs = []
            for pair_data in data["pairs"]:
                if pair_data.get("chainId") == self.chain_id:
                    pairs.append(TokenPair.from_api_response(pair_data))
            return pairs
        return []
    
    async def get_token_pairs(self, token_address: str) -> List[TokenPair]:
        """Get all pools for a specific token"""
        data = await self._make_request(f"/token-pairs/v1/{self.chain_id}/{token_address}")
        if data and isinstance(data, list):
            return [TokenPair.from_api_response(p) for p in data]
        return []
    
    async def get_all_megaeth_pairs(self) -> List[TokenPair]:
        """Search for all MegaETH pairs"""
        all_pairs = []
        search_queries = ["WETH", "ETH", "USD", "MEGA"]
        
        for query in search_queries:
            pairs = await self.search_pairs(query)
            for pair in pairs:
                if pair.chain_id == self.chain_id:
                    if not any(p.pair_address == pair.pair_address for p in all_pairs):
                        all_pairs.append(pair)
            await asyncio.sleep(0.2)
        
        return all_pairs


dex_client = DexScreenerClient()
