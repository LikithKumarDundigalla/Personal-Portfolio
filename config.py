import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "finance.db")

# --- Email settings (fill these in Settings tab or directly here) ---
EMAIL_SENDER = ""
EMAIL_PASSWORD = ""   # Use Gmail App Password, not your real password
EMAIL_RECEIVER = ""

# --- Scheduler settings ---
REMINDER_DAY = 1          # Day of month to send loan payment reminder (1-28)
PRICE_UPDATE_HOUR = 18    # Hour (24h) to fetch updated stock prices daily
PRICE_UPDATE_MINUTE = 0