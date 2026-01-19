
async def ensure_logged_in(user_id):
    """Ensures the user session is loaded if it exists on disk."""
    if user_id in active_sessions:
        return True
    
    # Check disk
    user_folder = os.path.join(USERS_DIR, str(user_id))
    # We create a UserSession wrapper to check validity
    # Note: UserSession requires API credentials. 
    # We assume API_ID/HASH are global in bot.py
    user_session = UserSession(user_id, API_ID, API_HASH, bot)
    
    if await user_session.is_authorized():
        # Valid session found on disk, load it
        await user_session.start()
        active_sessions[user_id] = user_session
        return True
    return False
