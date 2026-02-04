"""
Mogra API Client
Handles AI-powered chat conversations via Mogra API
"""
import aiohttp
import asyncio
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import logging

from config import config

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """Represents a chat message"""
    role: str
    content: str


@dataclass
class Chat:
    """Represents a chat session"""
    id: str
    title: str
    processing: bool
    messages: List[ChatMessage]
    
    @classmethod
    def from_api_response(cls, data: Dict[str, Any]) -> "Chat":
        """Parse API response into Chat object"""
        messages = []
        for msg in data.get("messages", []):
            messages.append(ChatMessage(
                role=msg.get("role", "user"),
                content=msg.get("content", "")
            ))
        
        return cls(
            id=data.get("id", ""),
            title=data.get("title", "New Chat"),
            processing=data.get("processing", False),
            messages=messages
        )


class MograClient:
    """Client for interacting with Mogra API"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.base_url = config.MOGRA_BASE_URL
        self.api_key = api_key or config.MOGRA_API_KEY
        self._session: Optional[aiohttp.ClientSession] = None
        self._user_chats: Dict[int, str] = {}
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                timeout=timeout
            )
        return self._session
    
    async def close(self):
        """Close the aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Make HTTP request to Mogra API"""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with session.request(method, url, params=params, json=json_data) as response:
                if response.status in [200, 201]:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(f"Mogra API error: {response.status} - {error_text}")
                    return {"error": error_text, "status": response.status}
        except Exception as e:
            logger.error(f"HTTP request failed: {e}")
            return {"error": str(e)}
    
    async def send_message(self, chat_id: str, message: str) -> Dict[str, Any]:
        """Send a message to a chat"""
        data = await self._make_request(
            "POST",
            "/chat/message",
            json_data={"chatId": chat_id, "message": message}
        )
        return data or {"error": "Failed to send message"}
    
    async def list_chats(self, page: int = 1, limit: int = 10) -> Dict[str, Any]:
        """List all chats"""
        data = await self._make_request("GET", "/chats", params={"page": page, "limit": limit})
        return data or {"chats": [], "total": 0}
    
    async def get_chat_info(self, chat_id: str) -> Optional[Chat]:
        """Get detailed chat information"""
        data = await self._make_request("GET", f"/chats/{chat_id}")
        if data and "error" not in data:
            return Chat.from_api_response(data)
        return None
    
    async def wait_for_response(self, chat_id: str, timeout: int = 60) -> Optional[str]:
        """Wait for AI response by polling chat status"""
        start_time = asyncio.get_event_loop().time()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                return None
            
            chat = await self.get_chat_info(chat_id)
            if chat is None:
                return None
            
            if not chat.processing:
                for msg in reversed(chat.messages):
                    if msg.role == "assistant":
                        return msg.content
                return None
            
            await asyncio.sleep(1)
    
    async def send_and_wait(self, chat_id: str, message: str, timeout: int = 60) -> Optional[str]:
        """Send a message and wait for the AI response"""
        result = await self.send_message(chat_id, message)
        if "error" in result:
            return None
        return await self.wait_for_response(chat_id, timeout)
    
    def get_user_chat_id(self, telegram_user_id: int) -> Optional[str]:
        return self._user_chats.get(telegram_user_id)
    
    def set_user_chat_id(self, telegram_user_id: int, chat_id: str):
        self._user_chats[telegram_user_id] = chat_id
    
    async def get_or_create_chat(self, telegram_user_id: int) -> Optional[str]:
        """Get existing chat or return first available"""
        existing_chat_id = self.get_user_chat_id(telegram_user_id)
        if existing_chat_id:
            chat = await self.get_chat_info(existing_chat_id)
            if chat:
                return existing_chat_id
        
        chats_data = await self.list_chats(page=1, limit=1)
        if chats_data.get("chats"):
            chat_id = chats_data["chats"][0].get("id")
            if chat_id:
                self.set_user_chat_id(telegram_user_id, chat_id)
                return chat_id
        
        return None


mogra_client = MograClient()
