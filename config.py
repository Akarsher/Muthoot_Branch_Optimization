import os
from dotenv import load_dotenv

load_dotenv()
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")

# Flask secret key for sessions (set in .env as SECRET_KEY). Fallback for dev only.
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

# Database Configuration
DB_PATH = "data/branches.db"

# Route Planning Configuration
MAX_DISTANCE_PER_DAY = 180_000  # 180 km in meters
MAX_LOCATIONS_PER_REQUEST = 25  # Google API limit

# Debug Settings
DEBUG_MODE = os.getenv("DEBUG_MODE", "True").lower() == "true"
VERBOSE_LOGGING = os.getenv("VERBOSE_LOGGING", "True").lower() == "true"

# Map Configuration
DEFAULT_MAP_CENTER = [10.0236, 76.5656]  # Kerala, India
DEFAULT_ZOOM_LEVEL = 11
