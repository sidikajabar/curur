"""
Database Manager
SQLite database for tracking seen tokens, user settings, and alert history
Supports Railway persistent storage
"""
import os
import asyncio
from typing import List, Dict, Any, Optional, Set
import logging
import aiosqlite

from config import config

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite database for the bot"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DATABASE_PATH
        self._connection: Optional[aiosqlite.Connection] = None
        
        # Ensure directory exists for Railway
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
    
    async def connect(self):
        """Connect to the database"""
        self._connection = await aiosqlite.connect(self.db_path)
        await self._create_tables()
        logger.info(f"Database connected: {self.db_path}")
    
    async def close(self):
        """Close the database connection"""
        if self._connection:
            await self._connection.close()
    
    async def _create_tables(self):
        """Create necessary tables if they don't exist"""
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    mogra_chat_id TEXT,
                    alerts_enabled BOOLEAN DEFAULT 1,
                    min_volume_usd REAL DEFAULT 1000,
                    min_liquidity_usd REAL DEFAULT 500,
                    price_change_threshold REAL DEFAULT 10.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    chat_id INTEGER,
                    subscription_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id),
                    UNIQUE(telegram_id, chat_id, subscription_type)
                )
            """)
            
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_tokens (
                    pair_address TEXT PRIMARY KEY,
                    token_symbol TEXT,
                    token_name TEXT,
                    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_alert_at TIMESTAMP,
                    alert_count INTEGER DEFAULT 0
                )
            """)
            
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    chat_id INTEGER,
                    pair_address TEXT,
                    alert_type TEXT,
                    message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS watched_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER,
                    token_address TEXT,
                    token_symbol TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(telegram_id, token_address)
                )
            """)
            
            # Portal tables
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS portals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portal_id TEXT UNIQUE,
                    owner_id INTEGER,
                    public_channel_id INTEGER,
                    public_channel_username TEXT,
                    private_group_id INTEGER,
                    private_group_title TEXT,
                    welcome_message TEXT,
                    verification_type TEXT DEFAULT 'button',
                    captcha_enabled BOOLEAN DEFAULT 0,
                    min_account_age_days INTEGER DEFAULT 0,
                    require_profile_photo BOOLEAN DEFAULT 0,
                    require_username BOOLEAN DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS portal_verifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portal_id TEXT,
                    user_id INTEGER,
                    username TEXT,
                    status TEXT DEFAULT 'pending',
                    verified_at TIMESTAMP,
                    invite_link TEXT,
                    invite_expires_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (portal_id) REFERENCES portals(portal_id)
                )
            """)
            
            await cursor.execute("""
                CREATE TABLE IF NOT EXISTS portal_banned_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portal_id TEXT,
                    user_id INTEGER,
                    reason TEXT,
                    banned_by INTEGER,
                    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (portal_id) REFERENCES portals(portal_id),
                    UNIQUE(portal_id, user_id)
                )
            """)
            
            await self._connection.commit()
    
    async def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user by Telegram ID"""
        async with self._connection.cursor() as cursor:
            await cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            row = await cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
        return None
    
    async def create_or_update_user(self, telegram_id: int, username: str = None, mogra_chat_id: str = None) -> bool:
        """Create or update a user"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    INSERT INTO users (telegram_id, username, mogra_chat_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT(telegram_id) DO UPDATE SET
                        username = COALESCE(excluded.username, users.username),
                        mogra_chat_id = COALESCE(excluded.mogra_chat_id, users.mogra_chat_id),
                        updated_at = CURRENT_TIMESTAMP
                """, (telegram_id, username, mogra_chat_id))
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error creating/updating user: {e}")
            return False
    
    async def update_user_settings(self, telegram_id: int, alerts_enabled: bool = None,
                                    min_volume_usd: float = None, min_liquidity_usd: float = None,
                                    price_change_threshold: float = None) -> bool:
        """Update user alert settings"""
        try:
            updates = []
            params = []
            
            if alerts_enabled is not None:
                updates.append("alerts_enabled = ?")
                params.append(alerts_enabled)
            if min_volume_usd is not None:
                updates.append("min_volume_usd = ?")
                params.append(min_volume_usd)
            if min_liquidity_usd is not None:
                updates.append("min_liquidity_usd = ?")
                params.append(min_liquidity_usd)
            if price_change_threshold is not None:
                updates.append("price_change_threshold = ?")
                params.append(price_change_threshold)
            
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(telegram_id)
                
                async with self._connection.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE users SET {', '.join(updates)} WHERE telegram_id = ?",
                        params
                    )
                    await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating user settings: {e}")
            return False
    
    async def add_subscription(self, telegram_id: int, chat_id: int, subscription_type: str = "all") -> bool:
        """Add a subscription for alerts"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    INSERT OR IGNORE INTO subscriptions (telegram_id, chat_id, subscription_type)
                    VALUES (?, ?, ?)
                """, (telegram_id, chat_id, subscription_type))
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding subscription: {e}")
            return False
    
    async def remove_subscription(self, telegram_id: int, chat_id: int) -> bool:
        """Remove a subscription"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM subscriptions WHERE telegram_id = ? AND chat_id = ?",
                    (telegram_id, chat_id)
                )
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error removing subscription: {e}")
            return False
    
    async def get_all_subscriptions(self) -> List[Dict[str, Any]]:
        """Get all active subscriptions"""
        async with self._connection.cursor() as cursor:
            await cursor.execute("""
                SELECT s.*, u.alerts_enabled, u.min_volume_usd, u.min_liquidity_usd, u.price_change_threshold
                FROM subscriptions s
                JOIN users u ON s.telegram_id = u.telegram_id
                WHERE u.alerts_enabled = 1
            """)
            rows = await cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    async def is_token_seen(self, pair_address: str) -> bool:
        """Check if a token pair has been seen before"""
        async with self._connection.cursor() as cursor:
            await cursor.execute("SELECT 1 FROM seen_tokens WHERE pair_address = ?", (pair_address,))
            return await cursor.fetchone() is not None
    
    async def mark_token_seen(self, pair_address: str, token_symbol: str, token_name: str) -> bool:
        """Mark a token as seen"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    INSERT INTO seen_tokens (pair_address, token_symbol, token_name, last_alert_at, alert_count)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)
                    ON CONFLICT(pair_address) DO UPDATE SET
                        last_alert_at = CURRENT_TIMESTAMP,
                        alert_count = seen_tokens.alert_count + 1
                """, (pair_address, token_symbol, token_name))
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error marking token as seen: {e}")
            return False
    
    async def get_seen_pair_addresses(self) -> Set[str]:
        """Get all seen pair addresses"""
        async with self._connection.cursor() as cursor:
            await cursor.execute("SELECT pair_address FROM seen_tokens")
            rows = await cursor.fetchall()
            return {row[0] for row in rows}
    
    async def log_alert(self, telegram_id: int, chat_id: int, pair_address: str, 
                        alert_type: str, message: str) -> bool:
        """Log an alert that was sent"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    INSERT INTO alert_history (telegram_id, chat_id, pair_address, alert_type, message)
                    VALUES (?, ?, ?, ?, ?)
                """, (telegram_id, chat_id, pair_address, alert_type, message))
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error logging alert: {e}")
            return False
    
    # ==================== PORTAL METHODS ====================
    
    async def create_portal(self, portal_id: str, owner_id: int, public_channel_id: int,
                           public_channel_username: str, private_group_id: int,
                           private_group_title: str, welcome_message: str = None) -> bool:
        """Create a new portal"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    INSERT INTO portals (portal_id, owner_id, public_channel_id, public_channel_username,
                                        private_group_id, private_group_title, welcome_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(portal_id) DO UPDATE SET
                        public_channel_id = excluded.public_channel_id,
                        public_channel_username = excluded.public_channel_username,
                        private_group_id = excluded.private_group_id,
                        private_group_title = excluded.private_group_title,
                        welcome_message = excluded.welcome_message,
                        updated_at = CURRENT_TIMESTAMP
                """, (portal_id, owner_id, public_channel_id, public_channel_username,
                      private_group_id, private_group_title, welcome_message))
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error creating portal: {e}")
            return False
    
    async def get_portal(self, portal_id: str) -> Optional[Dict[str, Any]]:
        """Get portal by ID"""
        async with self._connection.cursor() as cursor:
            await cursor.execute("SELECT * FROM portals WHERE portal_id = ?", (portal_id,))
            row = await cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
        return None
    
    async def get_portal_by_channel(self, channel_id: int) -> Optional[Dict[str, Any]]:
        """Get portal by public channel ID"""
        async with self._connection.cursor() as cursor:
            await cursor.execute("SELECT * FROM portals WHERE public_channel_id = ? AND is_active = 1", (channel_id,))
            row = await cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
        return None
    
    async def get_portal_by_private_group(self, group_id: int) -> Optional[Dict[str, Any]]:
        """Get portal by private group ID"""
        async with self._connection.cursor() as cursor:
            await cursor.execute("SELECT * FROM portals WHERE private_group_id = ? AND is_active = 1", (group_id,))
            row = await cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
        return None
    
    async def get_user_portals(self, owner_id: int) -> List[Dict[str, Any]]:
        """Get all portals owned by a user"""
        async with self._connection.cursor() as cursor:
            await cursor.execute("SELECT * FROM portals WHERE owner_id = ?", (owner_id,))
            rows = await cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in rows]
    
    async def update_portal_settings(self, portal_id: str, **kwargs) -> bool:
        """Update portal settings"""
        try:
            allowed_fields = ['welcome_message', 'verification_type', 'captcha_enabled',
                            'min_account_age_days', 'require_profile_photo', 'require_username', 'is_active']
            updates = []
            params = []
            
            for field, value in kwargs.items():
                if field in allowed_fields:
                    updates.append(f"{field} = ?")
                    params.append(value)
            
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(portal_id)
                
                async with self._connection.cursor() as cursor:
                    await cursor.execute(
                        f"UPDATE portals SET {', '.join(updates)} WHERE portal_id = ?",
                        params
                    )
                    await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating portal: {e}")
            return False
    
    async def delete_portal(self, portal_id: str) -> bool:
        """Delete a portal"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute("DELETE FROM portal_verifications WHERE portal_id = ?", (portal_id,))
                await cursor.execute("DELETE FROM portal_banned_users WHERE portal_id = ?", (portal_id,))
                await cursor.execute("DELETE FROM portals WHERE portal_id = ?", (portal_id,))
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting portal: {e}")
            return False
    
    async def create_verification(self, portal_id: str, user_id: int, username: str = None) -> bool:
        """Create a verification record"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    INSERT INTO portal_verifications (portal_id, user_id, username, status)
                    VALUES (?, ?, ?, 'pending')
                    ON CONFLICT DO NOTHING
                """, (portal_id, user_id, username))
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error creating verification: {e}")
            return False
    
    async def update_verification(self, portal_id: str, user_id: int, status: str,
                                  invite_link: str = None, invite_expires_at: str = None) -> bool:
        """Update verification status"""
        try:
            async with self._connection.cursor() as cursor:
                if status == 'verified':
                    await cursor.execute("""
                        UPDATE portal_verifications 
                        SET status = ?, verified_at = CURRENT_TIMESTAMP, invite_link = ?, invite_expires_at = ?
                        WHERE portal_id = ? AND user_id = ?
                    """, (status, invite_link, invite_expires_at, portal_id, user_id))
                else:
                    await cursor.execute("""
                        UPDATE portal_verifications SET status = ? WHERE portal_id = ? AND user_id = ?
                    """, (status, portal_id, user_id))
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating verification: {e}")
            return False
    
    async def get_verification(self, portal_id: str, user_id: int) -> Optional[Dict[str, Any]]:
        """Get verification record"""
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT * FROM portal_verifications WHERE portal_id = ? AND user_id = ?",
                (portal_id, user_id)
            )
            row = await cursor.fetchone()
            if row:
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, row))
        return None
    
    async def is_user_banned(self, portal_id: str, user_id: int) -> bool:
        """Check if user is banned from portal"""
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT 1 FROM portal_banned_users WHERE portal_id = ? AND user_id = ?",
                (portal_id, user_id)
            )
            return await cursor.fetchone() is not None
    
    async def ban_user(self, portal_id: str, user_id: int, reason: str, banned_by: int) -> bool:
        """Ban a user from portal"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute("""
                    INSERT OR REPLACE INTO portal_banned_users (portal_id, user_id, reason, banned_by)
                    VALUES (?, ?, ?, ?)
                """, (portal_id, user_id, reason, banned_by))
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error banning user: {e}")
            return False
    
    async def unban_user(self, portal_id: str, user_id: int) -> bool:
        """Unban a user from portal"""
        try:
            async with self._connection.cursor() as cursor:
                await cursor.execute(
                    "DELETE FROM portal_banned_users WHERE portal_id = ? AND user_id = ?",
                    (portal_id, user_id)
                )
                await self._connection.commit()
            return True
        except Exception as e:
            logger.error(f"Error unbanning user: {e}")
            return False
    
    async def get_portal_stats(self, portal_id: str) -> Dict[str, int]:
        """Get portal statistics"""
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "SELECT COUNT(*) FROM portal_verifications WHERE portal_id = ? AND status = 'verified'",
                (portal_id,)
            )
            verified = (await cursor.fetchone())[0]
            
            await cursor.execute(
                "SELECT COUNT(*) FROM portal_verifications WHERE portal_id = ? AND status = 'pending'",
                (portal_id,)
            )
            pending = (await cursor.fetchone())[0]
            
            await cursor.execute(
                "SELECT COUNT(*) FROM portal_banned_users WHERE portal_id = ?",
                (portal_id,)
            )
            banned = (await cursor.fetchone())[0]
            
            return {"verified": verified, "pending": pending, "banned": banned}


db = DatabaseManager()
