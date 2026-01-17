import asyncio
import os
import logging
import sys
import subprocess
from telethon import TelegramClient, events, errors, Button
from config import API_ID, API_HASH, BOT_TOKEN, USERS_DIR, ADMIN_ID, UPDATE_GROUP_ID
from user_handler import UserSession

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state
# {user_id: UserSession_instance}
active_sessions = {}

# {user_id: {'state': 'PHONE'|'OTP'|'2FA', 'client': TempClient, 'phone': str, 'phone_hash': str}}
login_states = {}

# Initialize Bot
bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

@bot.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    sender = await event.get_sender()
    if not sender: return
    user_id = sender.id
    
    logger.info(f"User {user_id} started the bot.")
    
    user_folder = os.path.join(USERS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    
    # Check if session exists and is loaded
    if await ensure_logged_in(user_id):
        # Already logged in or just loaded
        username = sender.first_name if sender else "User"
        await event.respond(f"Hey {username}\nWelcome to Ghost Catcher Bot\n\nYour account is ready to download self distruct (timer) images, videos and audios\n\nClick /fetch to get current chat list")
        return

    # No valid session
    username = sender.first_name if sender else "User"
    await event.respond(f"Hey {username}\nWelcome to Ghost Catcher Bot\n\nConnect your account to download any self distruct (timer) images, videos and audios\n\nClick /login to connect your account")

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
        await event.respond("Please send your Phone Number (with country code)\ne.g., +919876543210")
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

        await msg.edit(f"Update Successful\n\nOutput:\n{output}\n\nRestarting...")
        
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
             await event.respond("Please send your Phone Number (with country code)\ne.g., +919876543210")
             login_states[user_id] = {'state': 'PHONE'}
        else:
             await msg.edit(f"Error fetching chats: {e}")

@bot.on(events.NewMessage(pattern=r'/(\d+)'))
async def chat_scan_handler(event):
    user_id = event.sender_id
    
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
        for i, item in enumerate(results):
            path = item['path']
            name = item['sender_name']
            
            caption = ""
            if total == 1:
                caption = f"{name}"
            else:
                caption = f"{i+1}/{total}\n{name}"
            
            await bot.send_file(user_id, path, caption=caption)
        
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
             await event.respond("Please send your Phone Number (with country code)\ne.g., +919876543210")
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
                await client.disconnect() # Disconnect temp so UserSession can use the file
                
                # Start the persistent UserSession
                user_session = UserSession(user_id, API_ID, API_HASH, bot)
                await user_session.start()
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
                await client.disconnect()
                
                user_session = UserSession(user_id, API_ID, API_HASH, bot)
                await user_session.start()
                active_sessions[user_id] = user_session
                del login_states[user_id]
            except Exception as e:
                await event.respond("Incorrect password\nTry again")

    except Exception as e:
        logger.error(f"Error in handler: {e}")
        await event.respond("An internal error occurred.")

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

print("Bot is running...")
bot.loop.create_task(restore_sessions())
bot.run_until_disconnected()
