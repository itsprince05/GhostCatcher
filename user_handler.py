import os
import asyncio
from telethon import TelegramClient, events
from config import USERS_DIR

class UserSession:
    def __init__(self, user_id, api_id, api_hash, bot_instance):
        self.user_id = user_id
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot = bot_instance # The Bot instance to send messages back to the user
        self.client = None
        self.user_folder = os.path.join(USERS_DIR, str(user_id))
        self.download_folder = os.path.join(self.user_folder, "download")
        self.session_path = os.path.join(self.user_folder, "session") # .session will be appended by Telethon

        os.makedirs(self.download_folder, exist_ok=True)

    async def get_dialogs(self, limit=10):
        if not self.client:
            return []
        dialogs = await self.client.get_dialogs(limit=limit)
        return dialogs

    async def scan_chat_and_download(self, chat_id, limit=100):
        if not self.client:
            return 0, 0 # downloaded, total_checked

        count = 0
        total_media = 0
        media_paths = []
        sender_name = "Unknown"

        try:
            entity = await self.client.get_entity(int(chat_id))
            sender_name = getattr(entity, 'first_name', '') or getattr(entity, 'title', 'Unknown')
            
            async for message in self.client.iter_messages(entity, limit=limit):
                if message.ttl_seconds and message.media:
                    total_media += 1
                    path = await message.download_media(self.download_folder)
                    media_paths.append(path)
        except Exception as e:
            print(f"Error scanning chat {chat_id}: {e}")
            return [], "Error"

        return media_paths, sender_name

    async def start(self):
        """Starts the user client."""
        self.client = TelegramClient(self.session_path, self.api_id, self.api_hash)
        
        # Register hooks
        self.client.add_event_handler(self.on_new_message, events.NewMessage)
        
        await self.client.start()
        print(f"User {self.user_id} client started.")

    async def stop(self):
        if self.client:
            await self.client.disconnect()

    async def logout(self):
        """Logs out the user, disconnects, and deletes the session file."""
        await self.stop()
        if os.path.exists(self.session_path + ".session"):
            os.remove(self.session_path + ".session")
        print(f"User {self.user_id} logged out and session deleted.")

    async def is_authorized(self):
        """Checks if the session is valid."""
        if not os.path.exists(self.session_path + ".session"):
            return False
        
        try:
            # We need to temporarily connect to check auth
            temp_client = TelegramClient(self.session_path, self.api_id, self.api_hash)
            await temp_client.connect()
            is_auth = await temp_client.is_user_authorized()
            await temp_client.disconnect()
            return is_auth
        except Exception as e:
            print(f"Error checking auth for {self.user_id}: {e}")
            return False

    async def on_new_message(self, event):
        """Handles new messages for the user account."""
        try:
            # Check for self-destruct media (TTL)
            # Messages with ttl_seconds are usually photos/videos in secret chats or private messages (standard Telegram now allows TTL in generic PMs)
            if event.message.ttl_seconds and event.message.media:
                print(f"Detected self-destruct message for user {self.user_id}!")
                
                # Download
                path = await event.download_media(self.download_folder)
                print(f"Downloaded to {path}")
                
                # Send back to user via BOT
                # The user is the one interacting with the bot (user_id)
                await self.bot.send_message(self.user_id, "**Self-Destruct Detected!**\nI saved it for you:")
                await self.bot.send_file(self.user_id, path, caption="Recovered Media")
                
        except Exception as e:
            print(f"Error in message handler for {self.user_id}: {e}")
