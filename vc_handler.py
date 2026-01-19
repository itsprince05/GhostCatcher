import os
import asyncio
import logging

logger = logging.getLogger(__name__)

try:
    from pytgcalls import PyTgCalls
    from pytgcalls import idle
    from pytgcalls.types import Update
    from pytgcalls.types import GroupCallConfig
    from pytgcalls.types import AudioQuality
    from pytgcalls.types import AudioParameters
    # Depending on version, imports vary. Assuming generic structure or user will fix.
    HAS_VC = True
except ImportError:
    HAS_VC = False

class VCManager:
    def __init__(self, client, user_id):
        self.client = client
        self.user_id = user_id
        self.pytgcalls = None
        self.active_chat = None

    async def start_client(self):
        """Starts the PyTgCalls client for this user."""
        if not HAS_VC:
            logger.warning("PyTgCalls not installed. VC features disabled.")
            return False
            
        try:
            self.pytgcalls = PyTgCalls(self.client)
            await self.pytgcalls.start()
            logger.info(f"VC Client started for {self.user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to start VC Client: {e}")
            return False

    async def join_vc(self, chat_id):
        """Joins a Voice Chat in a Group/Channel."""
        if not HAS_VC or not self.pytgcalls:
            return "Voice Chat library not setup."
            
        try:
            # Join as Listener (Muted)
            await self.pytgcalls.join_group_call(
                int(chat_id),
                config=GroupCallConfig(
                    muted=True
                )
            )
            self.active_chat = chat_id
            return f"Joined Voice Chat in {chat_id}"
        except Exception as e:
            return f"Error Joining VC: {e}"

    async def leave_vc(self):
        """Leaves the current Voice Chat."""
        if not HAS_VC or not self.pytgcalls: return "Not connected."
        try:
            await self.pytgcalls.leave_group_call(self.active_chat)
            self.active_chat = None
            return "Left Voice Chat."
        except Exception as e:
            return f"Error Leaving: {e}"

    async def stop(self):
        if self.pytgcalls:
            try:
                await self.pytgcalls.stop() # Stops the client itself
            except: pass
