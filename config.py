"""
Configuration settings for the MegaETH Telegram Bot
Reads from environment variables (Railway compatible)
"""
import os

class Config:
    # Telegram Bot Token (get from @BotFather)
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    
    # Mogra API Configuration
    MOGRA_API_KEY: str = os.environ.get("MOGRA_API_KEY", "")
    MOGRA_BASE_URL: str = "https://mogra.xyz/api"
    
    # DexScreener API Configuration
    DEXSCREENER_BASE_URL: str = "https://api.dexscreener.com"
    MEGAETH_CHAIN_ID: str = "megaeth"
    
    # Alert Settings
    POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL", "30"))
    MIN_VOLUME_USD: float = float(os.environ.get("MIN_VOLUME_USD", "1000"))
    MIN_LIQUIDITY_USD: float = float(os.environ.get("MIN_LIQUIDITY_USD", "500"))
    PRICE_CHANGE_THRESHOLD: float = float(os.environ.get("PRICE_CHANGE_THRESHOLD", "10.0"))
    NEW_PAIR_AGE_MINUTES: int = int(os.environ.get("NEW_PAIR_AGE_MINUTES", "60"))
    
    # Database (SQLite for tracking seen tokens)
    DATABASE_PATH: str = os.environ.get("DATABASE_PATH", "/app/data/megaeth_bot.db")
    
    # Railway specific
    PORT: int = int(os.environ.get("PORT", "8080"))
    RAILWAY_ENVIRONMENT: str = os.environ.get("RAILWAY_ENVIRONMENT", "development")
    
    # Portal Settings
    PORTAL_INVITE_EXPIRY_MINUTES: int = int(os.environ.get("PORTAL_INVITE_EXPIRY_MINUTES", "5"))
    PORTAL_MAX_USES: int = int(os.environ.get("PORTAL_MAX_USES", "1"))


config = Config()
