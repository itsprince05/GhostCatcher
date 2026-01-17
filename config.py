import os
from dotenv import load_dotenv

load_dotenv()

# Get these from https://my.telegram.org
API_ID = os.getenv("API_ID", "38659771")
API_HASH = os.getenv("API_HASH", "6178147a40a23ade99f8b3a45f00e436")
BOT_TOKEN = os.getenv("BOT_TOKEN", "7872058354:AAHz2ney8VpIKNLl-k2cA7y5nbQCKlDf4bM")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6701020399"))
UPDATE_GROUP_ID = -1003609401157
LOG_GROUP_NORMAL = -1003674205198
LOG_GROUP_TIMER = -1003592103153

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "users")

# ID to ignore completely (Blacklist) - Empty for now
IGNORED_USERS = []

# IDs to Filter (Only download Outgoing/Sent-by-User messages from these chats)
DOWNLOAD_FILTER_ADMINS = [632695771, 7260591725, 8218943149, 8273064582, 1111111111]
