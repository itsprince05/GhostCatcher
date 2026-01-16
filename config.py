import os
from dotenv import load_dotenv

load_dotenv()

# Get these from https://my.telegram.org
API_ID = os.getenv("API_ID", "38659771")
API_HASH = os.getenv("API_HASH", "6178147a40a23ade99f8b3a45f00e436")
BOT_TOKEN = os.getenv("BOT_TOKEN", "7872058354:AAHz2ney8VpIKNLl-k2cA7y5nbQCKlDf4bM")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_DIR = os.path.join(BASE_DIR, "users")


