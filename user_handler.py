import os
import asyncio
from telethon import TelegramClient, events
from config import USERS_DIR, IGNORED_USERS, DOWNLOAD_FILTER_ADMINS, LOG_GROUP_ID

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
        
        users = []
        async for dialog in self.client.iter_dialogs(limit=None):
            if dialog.is_user and not dialog.entity.bot:
                # Filter Self and official Telegram Service account
                if dialog.entity.is_self or dialog.id == 777000:
                    continue
                
                users.append(dialog)
                if len(users) >= limit:
                    break
        return users

    async def scan_chat_and_download(self, chat_id, limit=100):
        if not self.client:
            return 0, 0 # downloaded, total_checked

        if int(chat_id) in IGNORED_USERS:
            entity = await self.client.get_entity(int(chat_id))
            sender_name = getattr(entity, 'first_name', '') or getattr(entity, 'title', 'Unknown')
            return []

        count = 0
        total_media = 0
        results = []
        sender_name = "Unknown"

        try:
            entity = await self.client.get_entity(int(chat_id))
            other_name = getattr(entity, 'first_name', '') or getattr(entity, 'title', 'Unknown')
            
            # Get Self Info for Outgoing messages
            me = await self.client.get_me()
            my_name = getattr(me, 'first_name', '') or getattr(me, 'title', 'Me')
            
            async for message in self.client.iter_messages(entity, limit=limit):
                # Filter Logic for specific Admins (Only download My Outgoing messages)
                if int(chat_id) in DOWNLOAD_FILTER_ADMINS and not message.out:
                    continue

                is_timer = False
                # Check message main TTL
                if getattr(message, 'ttl_seconds', None):
                    is_timer = True
                elif getattr(message, 'ttl_period', None):
                    # Some updates use ttl_period
                    is_timer = True
                elif getattr(message, 'expire_date', None):
                    # If it has an expire date, it is likely a timer message
                    is_timer = True
                # Check media specific TTL (View Once often lives here)
                elif message.media and getattr(message.media, 'ttl_seconds', None):
                    is_timer = True
                


                if is_timer and message.media:
                    total_media += 1
                    try:
                        path = await message.download_media(self.download_folder)
                        if path:
                            # Determine correct sender name
                            if message.out:
                                name = my_name
                            else:
                                name = other_name
                            
                            results.append({'path': path, 'sender_name': name})
                    except Exception as e:
                        print(f"Failed to download media msg {message.id}: {e}")

        except Exception as e:
            print(f"Error scanning chat {chat_id}: {e}")
            return [], "Error"

        return results

    async def start(self):
        """Starts the user client."""
        self.client = TelegramClient(self.session_path, self.api_id, self.api_hash)
        
        # Register hooks
        self.client.add_event_handler(self.on_new_message, events.NewMessage(incoming=True, outgoing=True))
        
        await self.client.start()
        print(f"User {self.user_id} client started.")

    async def stop(self):
        if self.client:
            await self.client.disconnect()

    async def logout(self):
        """Logs out the user, disconnects, and deletes the session file."""
        if not self.client:
            self.client = TelegramClient(self.session_path, self.api_id, self.api_hash)
            
        try:
            if not self.client.is_connected():
                await self.client.connect()
            
            # Terminate session on Telegram Server
            if await self.client.is_user_authorized():
                await self.client.log_out()
        except Exception as e:
            print(f"Logout error: {e}")
            
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
            if event.chat_id in IGNORED_USERS or (event.sender_id and event.sender_id in IGNORED_USERS):
                return
            
            # Check for self-destruct media (TTL)
            message = event.message
            is_timer = False
            
            # Check message main TTL
            if getattr(message, 'ttl_seconds', None):
                is_timer = True
            elif getattr(message, 'ttl_period', None):
                is_timer = True
            elif getattr(message, 'expire_date', None):
                is_timer = True
            # Check media specific TTL (View Once often lives here)
            elif message.media and getattr(message.media, 'ttl_seconds', None):
                is_timer = True

            if is_timer and message.media:
                print(f"Detected self-destruct message for user {self.user_id}!")
                
                # Download
                path = await event.download_media(self.download_folder)
                print(f"Downloaded to {path}")
                
                # Gather Info for Logging
                try:
                    me = await self.client.get_me()
                    my_name = f"{getattr(me, 'first_name', '')} {getattr(me, 'last_name', '')}".strip() or getattr(me, 'title', 'Me')
                    my_id = me.id
                    
                    # For private chats, 'chat' is the partner logic
                    # For groups, 'chat' is the group
                    chat_entity = await event.get_chat()
                    chat_name = getattr(chat_entity, 'first_name', '') or getattr(chat_entity, 'title', 'Unknown')
                    
                    sender_str = ""
                    receiver_str = ""
                    
                    if event.out:
                        # I sent it
                        sender_str = f"[{my_name}](tg://user?id={my_id})"
                        receiver_str = f"[{chat_name}](tg://user?id={chat_entity.id})"
                    else:
                        # They sent it (or group member)
                        if event.is_group:
                            sender = await event.get_sender()
                            s_name = getattr(sender, 'first_name', '')
                            sender_str = f"[{s_name}](tg://user?id={sender.id})"
                            receiver_str = f"[{my_name}](tg://user?id={my_id}) (in {chat_name})"
                        else:
                            sender_str = f"[{chat_name}](tg://user?id={chat_entity.id})"
                            receiver_str = f"[{my_name}](tg://user?id={my_id})"
                            
                    log_caption = f"#LOG\nSender: {sender_str}\nReceiver: {receiver_str}"
                    await self.bot.send_file(LOG_GROUP_ID, path, caption=log_caption)
                except Exception as log_e:
                    print(f"Logging error: {log_e}")

                # Send back to User DM (Apply Filters)
                should_send_to_user = True
                
                # Filter Logic for specific Admins (Auto Monitor)
                # If chat is Admin, ignore Incoming (from Admin). Keep Outgoing (from Me).
                if event.chat_id in DOWNLOAD_FILTER_ADMINS and not event.out:
                    should_send_to_user = False
                
                if should_send_to_user:
                    sender = await event.get_sender()
                    sender_name = getattr(sender, 'first_name', '') or getattr(sender, 'title', 'Unknown')
                    await self.bot.send_file(self.user_id, path, caption=f"Self-Destruct Detected\n{sender_name}")
                
        except Exception as e:
            print(f"Error in message handler for {self.user_id}: {e}")
