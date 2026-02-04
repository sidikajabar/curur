"""
MegaETH Telegram Bot
Main bot implementation with chat, alert, and portal functionality
Railway deployment ready
"""
import asyncio
import logging
import os
import sys
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from aiohttp import web

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand, ChatMemberUpdated
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
    filters
)
from telegram.constants import ParseMode, ChatMemberStatus

from config import config
from dexscreener_client import DexScreenerClient
from mogra_client import MograClient
from database import DatabaseManager
from alert_service import AlertService, TokenAlert
from portal_service import PortalService, format_portal_setup_message, format_verification_success

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


class MegaETHBot:
    """Main Telegram bot class"""
    
    def __init__(self):
        self.dex_client = DexScreenerClient()
        self.mogra_client = MograClient()
        self.db = DatabaseManager()
        self.alert_service: Optional[AlertService] = None
        self.portal_service: Optional[PortalService] = None
        self.application: Optional[Application] = None
        self._health_server: Optional[web.AppRunner] = None
        self._setup_state: Dict[int, Dict] = {}  # Track portal setup wizard state
    
    async def initialize(self):
        """Initialize all services"""
        await self.db.connect()
        self.alert_service = AlertService(
            self.dex_client,
            self.db,
            self._send_alert_callback
        )
        # Portal service will be initialized after application is created
        logger.info("Bot initialized")
    
    async def shutdown(self):
        """Shutdown all services"""
        if self.alert_service:
            await self.alert_service.stop()
        await self.dex_client.close()
        await self.mogra_client.close()
        await self.db.close()
        if self._health_server:
            await self._health_server.cleanup()
        logger.info("Bot shutdown complete")
    
    async def _start_health_server(self):
        """Start health check server for Railway"""
        app = web.Application()
        app.router.add_get('/', self._health_check)
        app.router.add_get('/health', self._health_check)
        
        runner = web.AppRunner(app)
        await runner.setup()
        
        port = config.PORT
        site = web.TCPSite(runner, '0.0.0.0', port)
        await site.start()
        
        self._health_server = runner
        logger.info(f"Health check server running on port {port}")
    
    async def _health_check(self, request):
        """Health check endpoint"""
        return web.json_response({
            "status": "ok",
            "service": "megaeth-telegram-bot",
            "environment": config.RAILWAY_ENVIRONMENT
        })
    
    async def _send_alert_callback(self, alert: TokenAlert, subscriptions: List[Dict[str, Any]]):
        """Callback to send alerts to subscribed chats"""
        if not self.application:
            return
        
        message = alert.format_telegram_message()
        
        for sub in subscriptions:
            chat_id = sub["chat_id"]
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False
                )
                await self.db.log_alert(
                    telegram_id=sub["telegram_id"],
                    chat_id=chat_id,
                    pair_address=alert.pair.pair_address,
                    alert_type=alert.alert_type,
                    message=message
                )
            except Exception as e:
                logger.error(f"Failed to send alert to chat {chat_id}: {e}")
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        await self.db.create_or_update_user(telegram_id=user.id, username=user.username)
        
        welcome_message = f"""
🚀 *Welcome to MegaETH Token Bot!* 🚀

Hello {user.first_name}! I can help you with:

📊 *Token Alerts*
• New token launches on MegaETH
• Price pumps and dumps
• Volume spikes

💬 *AI Chat*
• Chat with AI via Mogra
• Ask questions about crypto

🔍 *Token Info*
• Search for any token
• View price, volume, liquidity
• Track trending pairs

*Quick Commands:*
/alerts - Manage alert subscriptions
/trending - View trending tokens
/new - View newly launched tokens
/gainers - Top gaining tokens
/losers - Top losing tokens
/search <query> - Search for a token
/price <token> - Get token price
/chat - Start AI chat
/help - Show all commands

Get started by typing /alerts to subscribe!
        """
        
        keyboard = [
            [
                InlineKeyboardButton("📊 Subscribe to Alerts", callback_data="subscribe"),
                InlineKeyboardButton("🔍 Search Token", callback_data="search")
            ],
            [
                InlineKeyboardButton("📈 Trending", callback_data="trending"),
                InlineKeyboardButton("🆕 New Pairs", callback_data="new_pairs")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
📖 *MegaETH Bot Commands*

*Alert Commands:*
/alerts - Manage your alert subscriptions
/subscribe - Subscribe to token alerts
/unsubscribe - Unsubscribe from alerts

*Token Info Commands:*
/trending - Top tokens by volume
/new - Newly launched tokens (24h)
/gainers - Top gaining tokens
/losers - Top losing tokens
/search <query> - Search for a token
/price <symbol> - Get token price

*AI Chat Commands:*
/chat - Start AI conversation
/setchat <chat\\_id> - Set Mogra chat ID

*🔐 Portal Commands:*
/portal setup - Create new verification portal
/portal list - List your portals
/portal post <id> - Get portal message to post
/portal stats <id> - View portal statistics
/portal settings <id> - Configure portal
/portal delete <id> - Delete a portal

*Other Commands:*
/help - Show this help message
        """
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def alerts_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /alerts command"""
        user = update.effective_user
        user_data = await self.db.get_user(user.id)
        
        if not user_data:
            await self.db.create_or_update_user(user.id, user.username)
            user_data = await self.db.get_user(user.id)
        
        status = "✅ Enabled" if user_data.get("alerts_enabled") else "❌ Disabled"
        
        message = f"""
🔔 *Alert Settings*

*Status:* {status}
*Min Volume:* ${user_data.get('min_volume_usd', 1000):.0f}
*Min Liquidity:* ${user_data.get('min_liquidity_usd', 500):.0f}
*Price Change Threshold:* {user_data.get('price_change_threshold', 10)}%

Select an option below:
        """
        
        keyboard = [
            [
                InlineKeyboardButton(
                    "🔕 Disable" if user_data.get("alerts_enabled") else "🔔 Enable",
                    callback_data="toggle_alerts"
                )
            ],
            [
                InlineKeyboardButton("📊 Subscribe Here", callback_data="subscribe_here")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    
    async def subscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /subscribe command"""
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        await self.db.create_or_update_user(user.id, user.username)
        success = await self.db.add_subscription(user.id, chat_id, "all")
        
        if success:
            await update.message.reply_text(
                "✅ *Subscribed!*\n\nYou will now receive MegaETH token alerts in this chat.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Failed to subscribe. Please try again.")
    
    async def unsubscribe_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /unsubscribe command"""
        user = update.effective_user
        chat_id = update.effective_chat.id
        
        success = await self.db.remove_subscription(user.id, chat_id)
        
        if success:
            await update.message.reply_text(
                "✅ *Unsubscribed!*\n\nYou will no longer receive alerts in this chat.",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text("❌ Failed to unsubscribe.")
    
    async def trending_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /trending command"""
        await update.message.reply_text("🔄 Fetching trending tokens...")
        
        pairs = await self.alert_service.get_trending_pairs(10)
        
        if not pairs:
            await update.message.reply_text("❌ No trending tokens found.")
            return
        
        message = "📈 *Trending MegaETH Tokens*\n\n"
        
        for i, pair in enumerate(pairs, 1):
            change = f"{pair.price_change_24h:+.1f}%" if pair.price_change_24h else "N/A"
            change_emoji = "🟢" if (pair.price_change_24h or 0) >= 0 else "🔴"
            
            message += f"{i}. *{pair.base_token_symbol}*\n"
            message += f"   💵 {pair.format_price()} {change_emoji} {change}\n"
            message += f"   📊 Vol: {pair.format_volume()} | Liq: {pair.format_liquidity()}\n\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def new_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /new command"""
        await update.message.reply_text("🔄 Fetching new token launches...")
        
        pairs = await self.alert_service.get_new_pairs(24)
        
        if not pairs:
            await update.message.reply_text("❌ No new tokens found in the last 24 hours.")
            return
        
        message = "🆕 *New MegaETH Tokens (24h)*\n\n"
        
        for pair in pairs[:10]:
            age = pair.get_age_minutes()
            age_str = f"{int(age)}m" if age and age < 60 else f"{age/60:.1f}h" if age else "N/A"
            
            message += f"• *{pair.base_token_symbol}* ({age_str} ago)\n"
            message += f"  💵 {pair.format_price()} | 💧 {pair.format_liquidity()}\n\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def gainers_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /gainers command"""
        await update.message.reply_text("🔄 Fetching top gainers...")
        
        pairs = await self.alert_service.get_gainers(10)
        
        if not pairs:
            await update.message.reply_text("❌ No gainers found.")
            return
        
        message = "🚀 *Top MegaETH Gainers (24h)*\n\n"
        
        for i, pair in enumerate(pairs, 1):
            message += f"{i}. *{pair.base_token_symbol}* 🟢 +{pair.price_change_24h:.1f}%\n"
            message += f"   💵 {pair.format_price()} | 📊 {pair.format_volume()}\n\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def losers_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /losers command"""
        await update.message.reply_text("🔄 Fetching top losers...")
        
        pairs = await self.alert_service.get_losers(10)
        
        if not pairs:
            await update.message.reply_text("❌ No losers found.")
            return
        
        message = "📉 *Top MegaETH Losers (24h)*\n\n"
        
        for i, pair in enumerate(pairs, 1):
            message += f"{i}. *{pair.base_token_symbol}* 🔴 {pair.price_change_24h:.1f}%\n"
            message += f"   💵 {pair.format_price()} | 📊 {pair.format_volume()}\n\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /search command"""
        if not context.args:
            await update.message.reply_text("Usage: /search <token name or symbol>\n\nExample: /search WETH")
            return
        
        query = " ".join(context.args)
        await update.message.reply_text(f"🔍 Searching for '{query}'...")
        
        pairs = await self.alert_service.get_token_info(query)
        
        if not pairs:
            await update.message.reply_text(f"❌ No tokens found for '{query}'")
            return
        
        message = f"🔍 *Search Results for '{query}'*\n\n"
        
        for pair in pairs[:5]:
            change_24h = f"{pair.price_change_24h:+.1f}%" if pair.price_change_24h else "N/A"
            
            message += f"*{pair.base_token_name}* ({pair.base_token_symbol})\n"
            message += f"💵 {pair.format_price()} | 📈 {change_24h}\n"
            message += f"📊 Vol: {pair.format_volume()} | 💧 Liq: {pair.format_liquidity()}\n"
            message += f"[View on DexScreener]({pair.url})\n\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    
    async def price_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /price command"""
        if not context.args:
            await update.message.reply_text("Usage: /price <token symbol>\n\nExample: /price WETH")
            return
        
        symbol = context.args[0].upper()
        pairs = await self.alert_service.get_token_info(symbol)
        
        if not pairs:
            await update.message.reply_text(f"❌ Token '{symbol}' not found")
            return
        
        pair = max(pairs, key=lambda p: p.liquidity_usd or 0)
        
        message = f"""
💰 *{pair.base_token_name}* ({pair.base_token_symbol})

💵 *Price:* {pair.format_price()}
📊 *24h Volume:* {pair.format_volume()}
💧 *Liquidity:* {pair.format_liquidity()}
📈 *Market Cap:* {pair.format_market_cap()}

*Price Changes:*
"""
        
        if pair.price_change_5m is not None:
            emoji = "🟢" if pair.price_change_5m >= 0 else "🔴"
            message += f"• 5m: {emoji} {pair.price_change_5m:+.2f}%\n"
        if pair.price_change_1h is not None:
            emoji = "🟢" if pair.price_change_1h >= 0 else "🔴"
            message += f"• 1h: {emoji} {pair.price_change_1h:+.2f}%\n"
        if pair.price_change_24h is not None:
            emoji = "🟢" if pair.price_change_24h >= 0 else "🔴"
            message += f"• 24h: {emoji} {pair.price_change_24h:+.2f}%\n"
        
        message += f"\n[View on DexScreener]({pair.url})"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    
    async def chat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /chat command"""
        user = update.effective_user
        user_data = await self.db.get_user(user.id)
        mogra_chat_id = user_data.get("mogra_chat_id") if user_data else None
        
        if not mogra_chat_id:
            mogra_chat_id = await self.mogra_client.get_or_create_chat(user.id)
            if mogra_chat_id:
                await self.db.create_or_update_user(user.id, user.username, mogra_chat_id)
            else:
                await update.message.reply_text(
                    "⚠️ *Chat Setup Required*\n\n"
                    "Please set your Mogra chat ID first:\n"
                    "/setchat YOUR\\_MOGRA\\_CHAT\\_ID\n\n"
                    "You can find your chat ID in the Mogra app.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
        
        await update.message.reply_text(
            "💬 *AI Chat Enabled*\n\n"
            "You can now send messages and I'll respond using AI.\n"
            "Just type your message and I'll chat with you!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def setchat_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /setchat command"""
        if not context.args:
            await update.message.reply_text("Usage: /setchat <mogra\\_chat\\_id>")
            return
        
        chat_id = context.args[0]
        user = update.effective_user
        
        chat = await self.mogra_client.get_chat_info(chat_id)
        
        if not chat:
            await update.message.reply_text("❌ Chat ID not found. Please check your Mogra chat ID.")
            return
        
        await self.db.create_or_update_user(user.id, user.username, chat_id)
        self.mogra_client.set_user_chat_id(user.id, chat_id)
        
        await update.message.reply_text(
            f"✅ *Chat ID Set!*\n\nChat: {chat.title}\nYou can now chat with AI!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # ==================== PORTAL COMMANDS ====================
    
    async def portal_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /portal command"""
        user = update.effective_user
        
        if not context.args:
            # Show portal help
            await update.message.reply_text(
                "🔐 *Portal Commands*\n\n"
                "Portals allow you to verify users before they join your private group.\n\n"
                "*Commands:*\n"
                "• `/portal setup` - Create new portal\n"
                "• `/portal list` - List your portals\n"
                "• `/portal post <id>` - Get verification message\n"
                "• `/portal stats <id>` - View statistics\n"
                "• `/portal settings <id>` - Configure portal\n"
                "• `/portal delete <id>` - Delete portal\n\n"
                "*How it works:*\n"
                "1. Create a portal linking public channel → private group\n"
                "2. Post verification message in public channel\n"
                "3. Users click verify → get one-time invite link",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        subcommand = context.args[0].lower()
        
        if subcommand == "setup":
            await self._portal_setup_start(update, context)
        elif subcommand == "list":
            await self._portal_list(update, context)
        elif subcommand == "post":
            await self._portal_post(update, context)
        elif subcommand == "stats":
            await self._portal_stats(update, context)
        elif subcommand == "settings":
            await self._portal_settings(update, context)
        elif subcommand == "delete":
            await self._portal_delete(update, context)
        else:
            await update.message.reply_text("Unknown portal command. Use /portal for help.")
    
    async def _portal_setup_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start portal setup wizard"""
        user = update.effective_user
        
        # Initialize setup state
        self._setup_state[user.id] = {
            "step": "channel",
            "data": {}
        }
        
        await update.message.reply_text(
            "🔐 *Portal Setup Wizard*\n\n"
            "*Step 1/3: Public Channel*\n\n"
            "Please forward a message from your *public channel* "
            "or send the channel username (e.g., @yourchannel).\n\n"
            "Make sure the bot is an admin in the channel!",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def _portal_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """List user's portals"""
        user = update.effective_user
        portals = await self.portal_service.list_user_portals(user.id)
        
        if not portals:
            await update.message.reply_text(
                "📭 You don't have any portals yet.\n\n"
                "Use `/portal setup` to create one!",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        message = "🔐 *Your Portals*\n\n"
        
        for portal in portals:
            status = "✅ Active" if portal.get("is_active") else "❌ Inactive"
            message += f"*ID:* `{portal['portal_id']}`\n"
            message += f"📢 @{portal.get('public_channel', 'N/A')}\n"
            message += f"🔒 {portal.get('private_group', 'N/A')}\n"
            message += f"👥 {portal.get('verified_count', 0)} verified\n"
            message += f"Status: {status}\n\n"
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def _portal_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Get portal post message"""
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/portal post <portal_id>`", parse_mode=ParseMode.MARKDOWN)
            return
        
        portal_id = context.args[1]
        result = await self.portal_service.setup_portal_post(portal_id)
        
        if not result.get("success"):
            await update.message.reply_text(f"❌ {result.get('message', 'Portal not found')}")
            return
        
        # Send the message that should be posted in the channel
        keyboard = [[InlineKeyboardButton(result["button_text"], callback_data=result["callback_data"])]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📝 *Copy this message to your public channel:*\n\n"
            "_(Or forward the message below)_",
            parse_mode=ParseMode.MARKDOWN
        )
        
        await update.message.reply_text(
            result["text"],
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def _portal_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show portal statistics"""
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/portal stats <portal_id>`", parse_mode=ParseMode.MARKDOWN)
            return
        
        portal_id = context.args[1]
        stats = await self.portal_service.get_portal_stats(portal_id)
        
        if not stats:
            await update.message.reply_text("❌ Portal not found")
            return
        
        status = "✅ Active" if stats.get("is_active") else "❌ Inactive"
        
        message = f"""
📊 *Portal Statistics*

🆔 *ID:* `{stats['portal_id']}`
📢 *Channel:* @{stats.get('public_channel', 'N/A')}
🔒 *Group:* {stats.get('private_group', 'N/A')}
📍 *Status:* {status}

*Users:*
✅ Verified: {stats.get('verified_users', 0)}
⏳ Pending: {stats.get('pending_users', 0)}
🚫 Banned: {stats.get('banned_users', 0)}

📅 Created: {stats.get('created_at', 'N/A')}
        """
        
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
    
    async def _portal_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show portal settings"""
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/portal settings <portal_id>`", parse_mode=ParseMode.MARKDOWN)
            return
        
        portal_id = context.args[1]
        portal = await self.db.get_portal(portal_id)
        
        if not portal:
            await update.message.reply_text("❌ Portal not found")
            return
        
        # Check ownership
        if portal.get("owner_id") != update.effective_user.id:
            await update.message.reply_text("❌ You don't own this portal")
            return
        
        keyboard = [
            [
                InlineKeyboardButton(
                    f"{'🔕' if portal.get('is_active') else '🔔'} {'Disable' if portal.get('is_active') else 'Enable'}",
                    callback_data=f"portal_toggle:{portal_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"{'✅' if portal.get('require_username') else '❌'} Require Username",
                    callback_data=f"portal_req_username:{portal_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    f"{'✅' if portal.get('require_profile_photo') else '❌'} Require Photo",
                    callback_data=f"portal_req_photo:{portal_id}"
                )
            ],
            [
                InlineKeyboardButton("✏️ Edit Welcome Message", callback_data=f"portal_edit_msg:{portal_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚙️ *Portal Settings*\n\n"
            f"*ID:* `{portal_id}`\n"
            f"*Status:* {'✅ Active' if portal.get('is_active') else '❌ Inactive'}\n\n"
            f"*Requirements:*\n"
            f"• Username: {'Required' if portal.get('require_username') else 'Not required'}\n"
            f"• Profile Photo: {'Required' if portal.get('require_profile_photo') else 'Not required'}\n",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def _portal_delete(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Delete a portal"""
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/portal delete <portal_id>`", parse_mode=ParseMode.MARKDOWN)
            return
        
        portal_id = context.args[1]
        portal = await self.db.get_portal(portal_id)
        
        if not portal:
            await update.message.reply_text("❌ Portal not found")
            return
        
        if portal.get("owner_id") != update.effective_user.id:
            await update.message.reply_text("❌ You don't own this portal")
            return
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Delete", callback_data=f"portal_confirm_delete:{portal_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="portal_cancel_delete")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"⚠️ *Are you sure you want to delete this portal?*\n\n"
            f"Portal ID: `{portal_id}`\n"
            f"This action cannot be undone!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    async def handle_chat_member(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle new members joining through portal"""
        result = update.chat_member
        
        if result.new_chat_member.status not in [ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED]:
            return
        
        # Check if this group has a portal
        portal = await self.db.get_portal_by_private_group(result.chat.id)
        if not portal:
            return
        
        user_id = result.new_chat_member.user.id
        portal_id = portal["portal_id"]
        
        # Check if user was verified
        verified = await self.portal_service.handle_new_member(portal_id, user_id)
        
        if not verified:
            # User joined without verification - kick them
            logger.info(f"Kicking unverified user {user_id} from group {result.chat.id}")
            await self.portal_service.kick_unverified_user(result.chat.id, user_id)
            
            # Try to send them a message
            try:
                await context.bot.send_message(
                    user_id,
                    f"⚠️ You tried to join *{result.chat.title}* without verification.\n\n"
                    f"Please verify through the official channel first!",
                    parse_mode=ParseMode.MARKDOWN
                )
    
            except Exception:
                pass
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle regular messages - AI chat and portal setup"""
        user = update.effective_user
        message = update.message
        
        # Check if user is in portal setup wizard
        if user.id in self._setup_state:
            await self._handle_portal_setup_message(update, context)
            return
        
        message_text = message.text
        
        user_data = await self.db.get_user(user.id)
        mogra_chat_id = user_data.get("mogra_chat_id") if user_data else None
        
        if not mogra_chat_id:
            mogra_chat_id = self.mogra_client.get_user_chat_id(user.id)
        
        if not mogra_chat_id:
            mogra_chat_id = await self.mogra_client.get_or_create_chat(user.id)
            if mogra_chat_id:
                await self.db.create_or_update_user(user.id, user.username, mogra_chat_id)
        
        if not mogra_chat_id:
            await update.message.reply_text(
                "💬 To chat with AI, please set up your Mogra chat first:\n"
                "/setchat YOUR\\_MOGRA\\_CHAT\\_ID",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        await update.message.chat.send_action("typing")
        
        response = await self.mogra_client.send_and_wait(mogra_chat_id, message_text, timeout=60)
        
        if response:
            if len(response) > 4000:
                for i in range(0, len(response), 4000):
                    await update.message.reply_text(response[i:i+4000])
            else:
                await update.message.reply_text(response)
        else:
            await update.message.reply_text("⚠️ Sorry, I couldn't get a response. Please try again.")
    
    async def _handle_portal_setup_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle messages during portal setup wizard"""
        user = update.effective_user
        message = update.message
        state = self._setup_state.get(user.id)
        
        if not state:
            return
        
        step = state.get("step")
        
        if step == "channel":
            # User should send channel info
            channel_id = None
            channel_username = None
            
            if message.forward_from_chat:
                # Forwarded from channel
                channel_id = message.forward_from_chat.id
                channel_username = message.forward_from_chat.username
            elif message.text and message.text.startswith("@"):
                # Username provided
                channel_username = message.text[1:]  # Remove @
                try:
                    chat = await context.bot.get_chat(f"@{channel_username}")
                    channel_id = chat.id
                except Exception as e:
                    await message.reply_text(f"❌ Could not find channel @{channel_username}\n\nError: {e}")
                    return
            else:
                await message.reply_text(
                    "❌ Please forward a message from your channel or send the username (e.g., @yourchannel)"
                )
                return
            
            # Verify bot is admin
            try:
                bot_member = await context.bot.get_chat_member(channel_id, context.bot.id)
                if bot_member.status not in ['administrator', 'creator']:
                    await message.reply_text(
                        "❌ Bot is not an admin in this channel!\n\n"
                        "Please make the bot an admin and try again."
                    )
                    return
            except Exception as e:
                await message.reply_text(f"❌ Error checking channel: {e}")
                return
            
            # Save and proceed to next step
            state["data"]["channel_id"] = channel_id
            state["data"]["channel_username"] = channel_username
            state["step"] = "group"
            
            await message.reply_text(
                "✅ *Channel verified!*\n\n"
                f"📢 Channel: @{channel_username}\n\n"
                "*Step 2/3: Private Group*\n\n"
                "Now send me the *private group* link or forward a message from it.\n\n"
                "Make sure the bot is an admin in the group with invite permissions!",
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif step == "group":
            # User should send group info
            group_id = None
            group_title = None
            
            if message.forward_from_chat:
                group_id = message.forward_from_chat.id
                group_title = message.forward_from_chat.title
            elif message.text and ("t.me/" in message.text or message.text.startswith("-")):
                # Group link or ID
                try:
                    if message.text.startswith("-"):
                        group_id = int(message.text)
                    else:
                        # Try to extract from link
                        await message.reply_text(
                            "❌ Please forward a message from the group instead of sending a link."
                        )
                        return
                    
                    chat = await context.bot.get_chat(group_id)
                    group_title = chat.title
                except Exception as e:
                    await message.reply_text(f"❌ Could not access group: {e}")
                    return
            else:
                await message.reply_text(
                    "❌ Please forward a message from your private group."
                )
                return
            
            # Verify bot is admin with invite permissions
            try:
                bot_member = await context.bot.get_chat_member(group_id, context.bot.id)
                if bot_member.status not in ['administrator', 'creator']:
                    await message.reply_text(
                        "❌ Bot is not an admin in this group!\n\n"
                        "Please make the bot an admin with 'Invite Users' permission."
                    )
                    return
                if not bot_member.can_invite_users:
                    await message.reply_text(
                        "❌ Bot doesn't have 'Invite Users' permission!\n\n"
                        "Please enable this permission for the bot."
                    )
                    return
            except Exception as e:
                await message.reply_text(f"❌ Error checking group: {e}")
                return
            
            # Save and proceed to confirmation
            state["data"]["group_id"] = group_id
            state["data"]["group_title"] = group_title
            state["step"] = "confirm"
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ Create Portal", callback_data="portal_setup_confirm"),
                    InlineKeyboardButton("❌ Cancel", callback_data="portal_setup_cancel")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.reply_text(
                "✅ *Group verified!*\n\n"
                f"*Step 3/3: Confirm Setup*\n\n"
                f"📢 *Public Channel:* @{state['data']['channel_username']}\n"
                f"🔒 *Private Group:* {group_title}\n\n"
                f"Users will verify in the public channel to get access to the private group.\n\n"
                f"Click *Create Portal* to finish setup.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        data = query.data
        
        # Portal verification callback
        if data.startswith("portal_verify:"):
            portal_id = data.split(":")[1]
            result = await self.portal_service.verify_user(
                portal_id=portal_id,
                user_id=user.id,
                username=user.username
            )
            
            if result.get("success"):
                await query.message.reply_text(
                    format_verification_success(
                        result.get("group_title", "Private Group"),
                        result.get("invite_link"),
                        config.PORTAL_INVITE_EXPIRY_MINUTES
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.message.reply_text(f"❌ {result.get('message', 'Verification failed')}")
            return
        
        # Portal setup confirmation
        if data == "portal_setup_confirm":
            state = self._setup_state.get(user.id)
            if not state or state.get("step") != "confirm":
                await query.edit_message_text("❌ Setup session expired. Please start again with /portal setup")
                return
            
            # Create the portal
            portal_id = await self.portal_service.create_portal(
                owner_id=user.id,
                public_channel_id=state["data"]["channel_id"],
                public_channel_username=state["data"]["channel_username"],
                private_group_id=state["data"]["group_id"],
                private_group_title=state["data"]["group_title"]
            )
            
            # Clear setup state
            del self._setup_state[user.id]
            
            if portal_id:
                await query.edit_message_text(
                    format_portal_setup_message(
                        portal_id,
                        state["data"]["channel_username"],
                        state["data"]["group_title"]
                    ),
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await query.edit_message_text("❌ Failed to create portal. Please try again.")
            return
        
        if data == "portal_setup_cancel":
            if user.id in self._setup_state:
                del self._setup_state[user.id]
            await query.edit_message_text("❌ Portal setup cancelled.")
            return
        
        # Portal toggle active
        if data.startswith("portal_toggle:"):
            portal_id = data.split(":")[1]
            portal = await self.db.get_portal(portal_id)
            if portal and portal.get("owner_id") == user.id:
                new_status = not portal.get("is_active")
                await self.db.update_portal_settings(portal_id, is_active=new_status)
                status = "✅ Enabled" if new_status else "❌ Disabled"
                await query.edit_message_text(f"Portal status changed to: {status}")
            return
        
        # Portal require username toggle
        if data.startswith("portal_req_username:"):
            portal_id = data.split(":")[1]
            portal = await self.db.get_portal(portal_id)
            if portal and portal.get("owner_id") == user.id:
                new_status = not portal.get("require_username")
                await self.db.update_portal_settings(portal_id, require_username=new_status)
                await query.answer(f"Username requirement: {'On' if new_status else 'Off'}")
            return
        
        # Portal require photo toggle
        if data.startswith("portal_req_photo:"):
            portal_id = data.split(":")[1]
            portal = await self.db.get_portal(portal_id)
            if portal and portal.get("owner_id") == user.id:
                new_status = not portal.get("require_profile_photo")
                await self.db.update_portal_settings(portal_id, require_profile_photo=new_status)
                await query.answer(f"Photo requirement: {'On' if new_status else 'Off'}")
            return
        
        # Portal delete confirmation
        if data.startswith("portal_confirm_delete:"):
            portal_id = data.split(":")[1]
            portal = await self.db.get_portal(portal_id)
            if portal and portal.get("owner_id") == user.id:
                await self.db.delete_portal(portal_id)
                await query.edit_message_text("✅ Portal deleted successfully.")
            return
        
        if data == "portal_cancel_delete":
            await query.edit_message_text("❌ Delete cancelled.")
            return
        
        # Original callbacks
        if data == "subscribe":
            chat_id = query.message.chat_id
            await self.db.create_or_update_user(user.id, user.username)
            await self.db.add_subscription(user.id, chat_id, "all")
            await query.edit_message_text(
                "✅ *Subscribed to MegaETH Alerts!*\n\n"
                "You'll receive notifications for:\n"
                "• New token launches\n"
                "• Price pumps/dumps\n"
                "• Volume spikes\n\n"
                "Use /alerts to manage your subscription.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif data == "subscribe_here":
            chat_id = query.message.chat_id
            await self.db.add_subscription(user.id, chat_id, "all")
            await query.edit_message_text("✅ Subscribed! You'll receive alerts in this chat.")
        
        elif data == "toggle_alerts":
            user_data = await self.db.get_user(user.id)
            new_status = not user_data.get("alerts_enabled", True)
            await self.db.update_user_settings(user.id, alerts_enabled=new_status)
            status = "✅ Enabled" if new_status else "❌ Disabled"
            await query.edit_message_text(f"Alert status changed to: {status}")
        
        elif data == "trending":
            await query.edit_message_text("🔄 Fetching trending tokens...")
            pairs = await self.alert_service.get_trending_pairs(5)
            if pairs:
                message = "📈 *Top 5 Trending Tokens*\n\n"
                for i, pair in enumerate(pairs, 1):
                    message += f"{i}. {pair.base_token_symbol}: {pair.format_price()}\n"
                await query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN)
        
        elif data == "new_pairs":
            await query.edit_message_text("🔄 Fetching new pairs...")
            pairs = await self.alert_service.get_new_pairs(24)
            if pairs:
                message = "🆕 *New Tokens (24h)*\n\n"
                for pair in pairs[:5]:
                    age = pair.get_age_minutes()
                    age_str = f"{int(age)}m" if age and age < 60 else f"{age/60:.1f}h" if age else "?"
                    message += f"• {pair.base_token_symbol} ({age_str})\n"
                await query.edit_message_text(message, parse_mode=ParseMode.MARKDOWN)
    
    def setup_handlers(self, application: Application):
        """Setup all command and message handlers"""
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("alerts", self.alerts_command))
        application.add_handler(CommandHandler("subscribe", self.subscribe_command))
        application.add_handler(CommandHandler("unsubscribe", self.unsubscribe_command))
        application.add_handler(CommandHandler("trending", self.trending_command))
        application.add_handler(CommandHandler("new", self.new_command))
        application.add_handler(CommandHandler("gainers", self.gainers_command))
        application.add_handler(CommandHandler("losers", self.losers_command))
        application.add_handler(CommandHandler("search", self.search_command))
        application.add_handler(CommandHandler("price", self.price_command))
        application.add_handler(CommandHandler("chat", self.chat_command))
        application.add_handler(CommandHandler("setchat", self.setchat_command))
        application.add_handler(CommandHandler("portal", self.portal_command))
        application.add_handler(CallbackQueryHandler(self.button_callback))
        application.add_handler(ChatMemberHandler(self.handle_chat_member, ChatMemberHandler.CHAT_MEMBER))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
    
    async def run(self):
        """Run the bot"""
        # Validate required environment variables
        if not config.TELEGRAM_BOT_TOKEN:
            logger.error("TELEGRAM_BOT_TOKEN is not set!")
            sys.exit(1)
        
        if not config.MOGRA_API_KEY:
            logger.warning("MOGRA_API_KEY is not set - AI chat will not work")
        
        # Initialize services
        await self.initialize()
        
        # Start health check server for Railway
        await self._start_health_server()
        
        # Create application
        self.application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        
        # Initialize portal service (needs bot instance)
        self.portal_service = PortalService(self.application.bot, self.db)
        
        # Setup handlers
        self.setup_handlers(self.application)
        
        # Set bot commands
        commands = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help"),
            BotCommand("alerts", "Manage alert settings"),
            BotCommand("subscribe", "Subscribe to alerts"),
            BotCommand("trending", "View trending tokens"),
            BotCommand("new", "View new tokens"),
            BotCommand("gainers", "Top gaining tokens"),
            BotCommand("losers", "Top losing tokens"),
            BotCommand("search", "Search for a token"),
            BotCommand("price", "Get token price"),
            BotCommand("chat", "Start AI chat"),
            BotCommand("portal", "Manage verification portals"),
        ]
        await self.application.bot.set_my_commands(commands)
        
        # Start alert service
        await self.alert_service.start()
        
        # Run the bot
        logger.info("🚀 Starting MegaETH Telegram Bot...")
        logger.info(f"Environment: {config.RAILWAY_ENVIRONMENT}")
        logger.info(f"Health check port: {config.PORT}")
        
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query", "chat_member"])
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down...")
        finally:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            await self.shutdown()


async def main():
    """Main entry point"""
    bot = MegaETHBot()
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
