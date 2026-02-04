"""
Portal Service
Handles portal verification similar to Safeguard Bot
Creates portal from public channel to verify users entering private group
"""
import asyncio
import secrets
import string
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging

from telegram import Bot, ChatPermissions
from telegram.error import TelegramError

from config import config
from database import DatabaseManager

logger = logging.getLogger(__name__)


class PortalService:
    """Service for managing verification portals"""
    
    def __init__(self, bot: Bot, db: DatabaseManager):
        self.bot = bot
        self.db = db
    
    def generate_portal_id(self, length: int = 8) -> str:
        """Generate a unique portal ID"""
        chars = string.ascii_lowercase + string.digits
        return ''.join(secrets.choice(chars) for _ in range(length))
    
    async def create_portal(
        self,
        owner_id: int,
        public_channel_id: int,
        public_channel_username: str,
        private_group_id: int,
        private_group_title: str,
        welcome_message: str = None
    ) -> Optional[str]:
        """
        Create a new portal linking public channel to private group
        
        Args:
            owner_id: Telegram ID of the portal owner
            public_channel_id: ID of the public channel
            public_channel_username: Username of public channel (without @)
            private_group_id: ID of the private group
            private_group_title: Title of the private group
            welcome_message: Custom welcome message for verification
        
        Returns:
            Portal ID if successful, None otherwise
        """
        portal_id = self.generate_portal_id()
        
        if not welcome_message:
            welcome_message = f"""
🔐 *Portal Verification*

Welcome! To join *{private_group_title}*, you need to verify yourself.

Click the button below to start verification.
            """
        
        success = await self.db.create_portal(
            portal_id=portal_id,
            owner_id=owner_id,
            public_channel_id=public_channel_id,
            public_channel_username=public_channel_username,
            private_group_id=private_group_id,
            private_group_title=private_group_title,
            welcome_message=welcome_message
        )
        
        if success:
            logger.info(f"Portal created: {portal_id} by user {owner_id}")
            return portal_id
        return None
    
    async def verify_user(
        self,
        portal_id: str,
        user_id: int,
        username: str = None
    ) -> Dict[str, Any]:
        """
        Verify a user and generate invite link
        
        Returns:
            Dict with 'success', 'invite_link', 'message', 'expires_at'
        """
        # Get portal info
        portal = await self.db.get_portal(portal_id)
        if not portal:
            return {"success": False, "message": "Portal not found"}
        
        if not portal.get("is_active"):
            return {"success": False, "message": "Portal is inactive"}
        
        # Check if user is banned
        if await self.db.is_user_banned(portal_id, user_id):
            return {"success": False, "message": "You are banned from this portal"}
        
        # Check verification requirements
        verification_result = await self._check_requirements(portal, user_id)
        if not verification_result["passed"]:
            return {"success": False, "message": verification_result["message"]}
        
        # Create verification record
        await self.db.create_verification(portal_id, user_id, username)
        
        # Generate invite link
        try:
            expire_date = datetime.now() + timedelta(minutes=config.PORTAL_INVITE_EXPIRY_MINUTES)
            
            invite_link = await self.bot.create_chat_invite_link(
                chat_id=portal["private_group_id"],
                member_limit=config.PORTAL_MAX_USES,
                expire_date=expire_date,
                name=f"Portal-{user_id}"
            )
            
            # Update verification status
            await self.db.update_verification(
                portal_id=portal_id,
                user_id=user_id,
                status="verified",
                invite_link=invite_link.invite_link,
                invite_expires_at=expire_date.isoformat()
            )
            
            logger.info(f"User {user_id} verified for portal {portal_id}")
            
            return {
                "success": True,
                "invite_link": invite_link.invite_link,
                "message": "Verification successful!",
                "expires_at": expire_date,
                "group_title": portal["private_group_title"]
            }
            
        except TelegramError as e:
            logger.error(f"Error creating invite link: {e}")
            return {"success": False, "message": f"Error creating invite link: {str(e)}"}
    
    async def _check_requirements(self, portal: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """Check if user meets portal requirements"""
        try:
            # Get user info from Telegram
            user = await self.bot.get_chat(user_id)
            
            # Check username requirement
            if portal.get("require_username") and not user.username:
                return {"passed": False, "message": "❌ You need to set a Telegram username to join"}
            
            # Check profile photo requirement
            if portal.get("require_profile_photo"):
                photos = await self.bot.get_user_profile_photos(user_id, limit=1)
                if photos.total_count == 0:
                    return {"passed": False, "message": "❌ You need to set a profile photo to join"}
            
            # Account age check would require additional API or data
            # For now, we skip this as Telegram doesn't expose account creation date
            
            return {"passed": True, "message": "All requirements met"}
            
        except TelegramError as e:
            logger.error(f"Error checking requirements: {e}")
            return {"passed": False, "message": f"Error checking requirements: {str(e)}"}
    
    async def get_portal_message(self, portal_id: str) -> Optional[str]:
        """Get the formatted portal message"""
        portal = await self.db.get_portal(portal_id)
        if not portal:
            return None
        return portal.get("welcome_message")
    
    async def setup_portal_post(
        self,
        portal_id: str,
        custom_message: str = None
    ) -> Dict[str, Any]:
        """
        Generate the portal post content for the public channel
        
        Returns:
            Dict with 'text' and 'button_text', 'callback_data'
        """
        portal = await self.db.get_portal(portal_id)
        if not portal:
            return {"success": False, "message": "Portal not found"}
        
        message = custom_message or portal.get("welcome_message") or f"""
🚀 *Join {portal['private_group_title']}*

🔐 This is a protected group. Click the button below to verify and get access.

✅ Verification is quick and easy
⏱️ Invite link expires in {config.PORTAL_INVITE_EXPIRY_MINUTES} minutes
🔒 One-time use link for security
        """
        
        return {
            "success": True,
            "text": message,
            "button_text": "🔓 Verify & Join",
            "callback_data": f"portal_verify:{portal_id}",
            "portal": portal
        }
    
    async def handle_new_member(self, portal_id: str, user_id: int) -> bool:
        """Handle when a new member joins through portal"""
        verification = await self.db.get_verification(portal_id, user_id)
        
        if verification and verification.get("status") == "verified":
            # User was verified, allow them
            await self.db.update_verification(portal_id, user_id, "joined")
            return True
        
        # User wasn't verified through portal
        return False
    
    async def kick_unverified_user(self, group_id: int, user_id: int) -> bool:
        """Kick an unverified user from the group"""
        try:
            await self.bot.ban_chat_member(group_id, user_id)
            await asyncio.sleep(1)
            await self.bot.unban_chat_member(group_id, user_id)  # Unban so they can try again
            return True
        except TelegramError as e:
            logger.error(f"Error kicking user: {e}")
            return False
    
    async def get_portal_stats(self, portal_id: str) -> Optional[Dict[str, Any]]:
        """Get portal statistics"""
        portal = await self.db.get_portal(portal_id)
        if not portal:
            return None
        
        stats = await self.db.get_portal_stats(portal_id)
        
        return {
            "portal_id": portal_id,
            "public_channel": portal.get("public_channel_username"),
            "private_group": portal.get("private_group_title"),
            "is_active": portal.get("is_active"),
            "verified_users": stats.get("verified", 0),
            "pending_users": stats.get("pending", 0),
            "banned_users": stats.get("banned", 0),
            "created_at": portal.get("created_at")
        }
    
    async def list_user_portals(self, owner_id: int) -> List[Dict[str, Any]]:
        """List all portals owned by a user"""
        portals = await self.db.get_user_portals(owner_id)
        result = []
        
        for portal in portals:
            stats = await self.db.get_portal_stats(portal["portal_id"])
            result.append({
                "portal_id": portal["portal_id"],
                "public_channel": portal.get("public_channel_username"),
                "private_group": portal.get("private_group_title"),
                "is_active": portal.get("is_active"),
                "verified_count": stats.get("verified", 0)
            })
        
        return result


def format_portal_setup_message(portal_id: str, public_channel: str, private_group: str) -> str:
    """Format the portal setup success message"""
    return f"""
✅ *Portal Created Successfully!*

🆔 *Portal ID:* `{portal_id}`
📢 *Public Channel:* @{public_channel}
🔒 *Private Group:* {private_group}

*Next Steps:*

1️⃣ Post the verification message in your public channel:
   Use `/portal post {portal_id}` to get the message

2️⃣ Make sure the bot is admin in both:
   • Public channel (to post messages)
   • Private group (to create invite links)

3️⃣ Users click "Verify & Join" → Get one-time invite link

*Management Commands:*
• `/portal stats {portal_id}` - View statistics
• `/portal settings {portal_id}` - Change settings
• `/portal delete {portal_id}` - Delete portal
    """


def format_verification_success(group_title: str, invite_link: str, expires_minutes: int) -> str:
    """Format the verification success message"""
    return f"""
✅ *Verification Successful!*

You can now join *{group_title}*

🔗 *Your Invite Link:*
{invite_link}

⚠️ *Important:*
• Link expires in {expires_minutes} minutes
• Link can only be used once
• Click the link above to join

Welcome aboard! 🎉
    """
