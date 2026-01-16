import asyncio
import os
import logging
from telethon import TelegramClient, events, errors, Button
from config import API_ID, API_HASH, BOT_TOKEN, USERS_DIR
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
    user_id = sender.id
    
    logger.info(f"User {user_id} started the bot.")
    
    user_folder = os.path.join(USERS_DIR, str(user_id))
    os.makedirs(user_folder, exist_ok=True)
    
    # Check if session exists and is loaded
    if user_id in active_sessions:
        username = sender.first_name if sender else "User"
        await event.respond(f"Hey {username}\nWelcome to Ghost Catcher Bot\n\nYour account is ready to download any self distruct (timer) images, videos and audios\n\nClick /fetch to get Current Chat List")
        return

    # Check if session file exists on disk
    session_path = os.path.join(user_folder, "session")
    
    # We create a UserSession wrapper to check validity
    user_session = UserSession(user_id, API_ID, API_HASH, bot)
    
    if await user_session.is_authorized():
        # Valid session found on disk
        await user_session.start()
        active_sessions[user_id] = user_session
        username = sender.first_name if sender else "User"
        await event.respond(f"Hey {username}\nWelcome to Ghost Catcher Bot\n\nYour account is ready to download any self distruct (timer) images, videos and audios\n\nClick /fetch to get Current Chat List")
    else:
        # No valid session
        username = sender.first_name if sender else "User"
        await event.respond(f"Hey {username}\nWelcome to Ghost Catcher Bot\n\nYour account is ready to download any self distruct (timer) images, videos and audios\nClick /login to connect your account")

@bot.on(events.NewMessage(pattern='/login'))
async def login_command(event):
    sender = await event.get_sender()
    user_id = sender.id
    username = sender.first_name if sender else "User"
    user_folder = os.path.join(USERS_DIR, str(user_id))
    session_path = os.path.join(user_folder, "session")

    # If already logged in (memory)
    if user_id in active_sessions:
        await event.respond(f"Hey {username}\nYour account is already connected and ready to use")
        return

    # Check disk
    user_session = UserSession(user_id, API_ID, API_HASH, bot)
    if await user_session.is_authorized():
        # Load it back up
        await user_session.start()
        active_sessions[user_id] = user_session
        await event.respond(f"Hey {username}\nYour account is already connected and ready to use")
    else:
        # Check if invalid session file exists (expired check)
        if os.path.exists(session_path + ".session"):
            try:
                os.remove(session_path + ".session")
                await event.respond(f"Hey {username}\nYour session is expired reconnect your account again and start catching self distruct (timer) media")
            except Exception as e:
                logger.error(f"Error removing session: {e}")
        else:
             await event.respond(f"Hey {username}\nConnect your account and start catching self distruct (timer) media")
        
        # Start Login Flow
        await event.respond("Please send your **Phone Number** (with country code, e.g., +919876543210).")
        login_states[user_id] = {'state': 'PHONE'}

@bot.on(events.NewMessage(pattern='/logout'))
async def logout_handler(event):
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

    # Force delete folder content if needed (UserSession.logout only deletes session file)
    # Re-verify deletion
    session_path = os.path.join(user_folder, "session.session")
    if os.path.exists(session_path):
        os.remove(session_path)

    await event.edit("Logged out successfully. Session deleted.")

@bot.on(events.CallbackQuery(pattern=b"logout_no"))
async def logout_cancel(event):
    await event.edit("Logout cancelled.")

@bot.on(events.NewMessage(pattern='/fetch'))
async def fetch_handler(event):
    user_id = event.sender_id
    if user_id not in active_sessions:
        await event.respond("You are not logged in. Use /login.")
        return
    
    msg = await event.respond("Fetching Chat List...")
    
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
            response_text = "No chats found."
            
        await msg.edit(response_text)
        
    except Exception as e:
        await msg.edit(f"Error fetching chats: {e}")

@bot.on(events.NewMessage(pattern=r'/(\d+)'))
async def chat_scan_handler(event):
    user_id = event.sender_id
    if user_id not in active_sessions:
        # Ignore random slashes if not logged in
        return
        
    target_id = int(event.pattern_match.group(1))
    # We stripped sign, but we might need to resolve it. 
    # The scan_chat function takes an ID. 
    # If the user listed was a group, it would be negative. 
    # If the listing only showed positive (abs), we might assume it's a user private chat.
    # The user asked for "userid" implying users.
    # Telethon .get_entity(id) usually handles positive integers as User IDs. (or Chat IDs).
    
    await event.respond(f"Scanning scan last 100 messages for ID {target_id}...")
    
    try:
        media_paths, sender_name = await active_sessions[user_id].scan_chat_and_download(target_id, limit=100)
        
        if not media_paths:
            await event.respond(f"No self-destruct media found for {target_id}.")
            return
            
        total = len(media_paths)
        for i, path in enumerate(media_paths):
            caption = ""
            if total == 1:
                caption = f"{sender_name}\nDone"
            else:
                caption = f"{i+1}/{total}\n{sender_name}\nDone"
            
            await bot.send_file(user_id, path, caption=caption)
            
    except Exception as e:
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
            await event.respond(f"Connecting to Telegram with {phone}...")
            
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
                    
                    await event.respond("OTP Sent!\nIf your OTP is 12345 then send by seperating with spaces like 1 2 3 4 5")
                except errors.FloodWaitError as e:
                    await event.respond(f"Flood Wait Error. Please wait {e.seconds} seconds.")
                    del login_states[user_id]
                except Exception as e:
                    await event.respond(f"Error: {str(e)}")
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
                
                await event.respond(f"Hey {username}\nYour account is already connected and ready to use")
                await client.disconnect() # Disconnect temp so UserSession can use the file
                
                # Start the persistent UserSession
                user_session = UserSession(user_id, API_ID, API_HASH, bot)
                await user_session.start()
                active_sessions[user_id] = user_session
                del login_states[user_id]
                
            except errors.SessionPasswordNeededError:
                state_data['state'] = '2FA'
                await event.respond("**Two-Step Verification Required**\nPlease enter your 2FA Password.")
            except Exception as e:
                await event.respond(f"Login failed: {str(e)}")

        elif state == '2FA':
            password = text
            client = state_data['client']
            
            try:
                await client.sign_in(password=password)
                await event.respond("**Login Successful!**\nSession saved. Monitoring started.")
                await client.disconnect()
                
                user_session = UserSession(user_id, API_ID, API_HASH, bot)
                await user_session.start()
                active_sessions[user_id] = user_session
                del login_states[user_id]
            except Exception as e:
                await event.respond(f"Password failed: {str(e)}")

    except Exception as e:
        logger.error(f"Error in handler: {e}")
        await event.respond("An internal error occurred.")

print("Bot is running...")
bot.run_until_disconnected()
