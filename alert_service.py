"""
Alert Service
Monitors MegaETH tokens via DexScreener and triggers alerts
"""
import asyncio
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime
import logging

from config import config
from dexscreener_client import DexScreenerClient, TokenPair
from database import DatabaseManager

logger = logging.getLogger(__name__)


class AlertType:
    NEW_PAIR = "new_pair"
    PRICE_PUMP = "price_pump"
    PRICE_DUMP = "price_dump"
    HIGH_VOLUME = "high_volume"


class TokenAlert:
    """Represents an alert to be sent"""
    
    def __init__(self, alert_type: str, pair: TokenPair, message: str, priority: int = 1):
        self.alert_type = alert_type
        self.pair = pair
        self.message = message
        self.priority = priority
        self.timestamp = datetime.now()
    
    def format_telegram_message(self) -> str:
        """Format the alert for Telegram"""
        emoji_map = {
            AlertType.NEW_PAIR: "🆕",
            AlertType.PRICE_PUMP: "🚀",
            AlertType.PRICE_DUMP: "📉",
            AlertType.HIGH_VOLUME: "📊",
        }
        
        emoji = emoji_map.get(self.alert_type, "🔔")
        
        lines = [
            f"{emoji} *{self.alert_type.replace('_', ' ').upper()}* {emoji}",
            "",
            f"*Token:* {self.pair.base_token_name} ({self.pair.base_token_symbol})",
            f"*Pair:* {self.pair.base_token_symbol}/{self.pair.quote_token_symbol}",
            f"*DEX:* {self.pair.dex_id}",
            "",
            f"💵 *Price:* {self.pair.format_price()}",
            f"📈 *Volume 24h:* {self.pair.format_volume()}",
            f"💧 *Liquidity:* {self.pair.format_liquidity()}",
            f"📊 *Market Cap:* {self.pair.format_market_cap()}",
        ]
        
        if self.pair.price_change_5m is not None:
            e = "🟢" if self.pair.price_change_5m >= 0 else "🔴"
            lines.append(f"{e} *5m:* {self.pair.price_change_5m:+.2f}%")
        if self.pair.price_change_1h is not None:
            e = "🟢" if self.pair.price_change_1h >= 0 else "🔴"
            lines.append(f"{e} *1h:* {self.pair.price_change_1h:+.2f}%")
        if self.pair.price_change_24h is not None:
            e = "🟢" if self.pair.price_change_24h >= 0 else "🔴"
            lines.append(f"{e} *24h:* {self.pair.price_change_24h:+.2f}%")
        
        total_txns = self.pair.txns_24h_buys + self.pair.txns_24h_sells
        if total_txns > 0:
            lines.append(f"🔄 *Txns 24h:* {total_txns} (🟢{self.pair.txns_24h_buys}/🔴{self.pair.txns_24h_sells})")
        
        age_minutes = self.pair.get_age_minutes()
        if age_minutes is not None:
            if age_minutes < 60:
                lines.append(f"⏱️ *Age:* {int(age_minutes)} minutes")
            elif age_minutes < 1440:
                lines.append(f"⏱️ *Age:* {age_minutes / 60:.1f} hours")
            else:
                lines.append(f"⏱️ *Age:* {age_minutes / 1440:.1f} days")
        
        lines.extend([
            "",
            f"🔗 [View on DexScreener]({self.pair.url})",
            "",
            f"📍 *Contract:* `{self.pair.base_token_address[:10]}...{self.pair.base_token_address[-8:]}`"
        ])
        
        return "\n".join(lines)


class AlertService:
    """Service for monitoring tokens and generating alerts"""
    
    def __init__(self, dex_client: DexScreenerClient, db: DatabaseManager,
                 alert_callback: Optional[Callable[[TokenAlert, List[Dict]], Any]] = None):
        self.dex_client = dex_client
        self.db = db
        self.alert_callback = alert_callback
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._previous_prices: Dict[str, float] = {}
        self._previous_volumes: Dict[str, float] = {}
    
    async def start(self):
        """Start the alert monitoring service"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Alert service started")
    
    async def stop(self):
        """Stop the alert monitoring service"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Alert service stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self._running:
            try:
                await self._check_for_alerts()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
            await asyncio.sleep(config.POLL_INTERVAL)
    
    async def _check_for_alerts(self):
        """Check for new tokens and price movements"""
        pairs = await self.dex_client.get_all_megaeth_pairs()
        if not pairs:
            return
        
        seen_addresses = await self.db.get_seen_pair_addresses()
        subscriptions = await self.db.get_all_subscriptions()
        
        if not subscriptions:
            return
        
        alerts = []
        
        for pair in pairs:
            if pair.pair_address not in seen_addresses:
                alert = await self._check_new_pair(pair)
                if alert:
                    alerts.append(alert)
                    await self.db.mark_token_seen(
                        pair.pair_address, pair.base_token_symbol, pair.base_token_name
                    )
            else:
                price_alert = self._check_price_movement(pair)
                if price_alert:
                    alerts.append(price_alert)
                
                volume_alert = self._check_volume_spike(pair)
                if volume_alert:
                    alerts.append(volume_alert)
            
            if pair.price_usd:
                try:
                    self._previous_prices[pair.pair_address] = float(pair.price_usd)
                except ValueError:
                    pass
            
            if pair.volume_24h:
                self._previous_volumes[pair.pair_address] = pair.volume_24h
        
        for alert in alerts:
            await self._send_alert(alert, subscriptions)
    
    async def _check_new_pair(self, pair: TokenPair) -> Optional[TokenAlert]:
        """Check if a new pair should trigger an alert"""
        if pair.liquidity_usd and pair.liquidity_usd < config.MIN_LIQUIDITY_USD:
            return None
        
        age_minutes = pair.get_age_minutes()
        if age_minutes is not None and age_minutes > config.NEW_PAIR_AGE_MINUTES:
            return None
        
        return TokenAlert(
            alert_type=AlertType.NEW_PAIR,
            pair=pair,
            message=f"New token detected: {pair.base_token_symbol}",
            priority=2
        )
    
    def _check_price_movement(self, pair: TokenPair) -> Optional[TokenAlert]:
        """Check for significant price movements"""
        if pair.price_change_1h is None:
            return None
        
        threshold = config.PRICE_CHANGE_THRESHOLD
        
        if pair.price_change_1h >= threshold:
            return TokenAlert(
                alert_type=AlertType.PRICE_PUMP,
                pair=pair,
                message=f"🚀 {pair.base_token_symbol} pumping! +{pair.price_change_1h:.1f}% in 1h",
                priority=3
            )
        elif pair.price_change_1h <= -threshold:
            return TokenAlert(
                alert_type=AlertType.PRICE_DUMP,
                pair=pair,
                message=f"📉 {pair.base_token_symbol} dumping! {pair.price_change_1h:.1f}% in 1h",
                priority=1
            )
        
        return None
    
    def _check_volume_spike(self, pair: TokenPair) -> Optional[TokenAlert]:
        """Check for volume spikes"""
        if not pair.volume_24h or pair.volume_24h < config.MIN_VOLUME_USD * 10:
            return None
        
        previous_volume = self._previous_volumes.get(pair.pair_address)
        if previous_volume is None:
            return None
        
        if pair.volume_24h >= previous_volume * 2:
            return TokenAlert(
                alert_type=AlertType.HIGH_VOLUME,
                pair=pair,
                message=f"📊 {pair.base_token_symbol} volume spike! {pair.format_volume()} 24h",
                priority=2
            )
        
        return None
    
    async def _send_alert(self, alert: TokenAlert, subscriptions: List[Dict[str, Any]]):
        """Send alert to all subscribed users/chats"""
        if self.alert_callback:
            try:
                await self.alert_callback(alert, subscriptions)
            except Exception as e:
                logger.error(f"Error sending alert: {e}")
    
    async def get_token_info(self, query: str) -> List[TokenPair]:
        """Search for token information"""
        return await self.dex_client.search_pairs(query)
    
    async def get_trending_pairs(self, limit: int = 10) -> List[TokenPair]:
        """Get trending pairs by volume"""
        pairs = await self.dex_client.get_all_megaeth_pairs()
        pairs_with_volume = [p for p in pairs if p.volume_24h]
        pairs_with_volume.sort(key=lambda p: p.volume_24h or 0, reverse=True)
        return pairs_with_volume[:limit]
    
    async def get_new_pairs(self, max_age_hours: int = 24) -> List[TokenPair]:
        """Get new pairs within the specified time"""
        pairs = await self.dex_client.get_all_megaeth_pairs()
        max_age_minutes = max_age_hours * 60
        new_pairs = []
        
        for pair in pairs:
            age = pair.get_age_minutes()
            if age is not None and age <= max_age_minutes:
                new_pairs.append(pair)
        
        new_pairs.sort(key=lambda p: p.get_age_minutes() or float('inf'))
        return new_pairs
    
    async def get_gainers(self, limit: int = 10) -> List[TokenPair]:
        """Get top gainers by price change"""
        pairs = await self.dex_client.get_all_megaeth_pairs()
        pairs_with_change = [p for p in pairs if p.price_change_24h is not None]
        pairs_with_change.sort(key=lambda p: p.price_change_24h or 0, reverse=True)
        return pairs_with_change[:limit]
    
    async def get_losers(self, limit: int = 10) -> List[TokenPair]:
        """Get top losers by price change"""
        pairs = await self.dex_client.get_all_megaeth_pairs()
        pairs_with_change = [p for p in pairs if p.price_change_24h is not None]
        pairs_with_change.sort(key=lambda p: p.price_change_24h or 0)
        return pairs_with_change[:limit]
