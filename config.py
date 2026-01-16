import os
from dotenv import load_dotenv

load_dotenv()

# Get these from https://my.telegram.org
API_ID = os.getenv("API_ID", "YOUR_API_ID_HERE")
API_HASH = os.getenv("API_HASH", "YOUR_API_HASH_HERE")
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "users")
