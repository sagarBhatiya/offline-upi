import os
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

class Config:
    """Centralized application configuration."""
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "offline_upi_super_secret_session_key_2026")
    
    # PostgreSQL Database URL (Supabase, Neon, Railway, Render, Docker, or Local)
    # Automatically fixes 'postgres://' scheme to 'postgresql://' if needed
    raw_db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
    if raw_db_url.startswith("postgres://"):
        raw_db_url = raw_db_url.replace("postgres://", "postgresql://", 1)
    DATABASE_URL = raw_db_url

    # Cashfree Gateway
    CASHFREE_APP_ID = os.environ.get("CASHFREE_APP_ID", "")
    CASHFREE_SECRET_KEY = os.environ.get("CASHFREE_SECRET_KEY", "")
    CASHFREE_ENVIRONMENT = os.environ.get("CASHFREE_ENVIRONMENT", "SANDBOX")
    PG_WEBHOOK_SECRET = os.environ.get("PG_WEBHOOK_SECRET", "pg_sandbox_webhook_secret_key_v1")

    # Server Settings
    PORT = int(os.environ.get("PORT", 5000))
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
