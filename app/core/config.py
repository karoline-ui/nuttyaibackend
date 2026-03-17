"""
app/core/config.py
"""
import os

class Settings:
    APP_NAME: str = "Nutty.AI"
    DEBUG: bool = os.environ.get("DEBUG", "false").lower() == "true"
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "nutty-secret-change-in-production")

    SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
    SUPABASE_ANON_KEY: str = os.environ.get("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_KEY: str = os.environ.get("SUPABASE_SERVICE_KEY", "")
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "")

    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    GEMINI_VISION_MODEL: str = os.environ.get("GEMINI_VISION_MODEL", "gemini-2.5-flash")

    UAZAP_BASE_URL: str = os.environ.get("UAZAP_BASE_URL", "https://api.uazap.com")
    UAZAP_API_KEY: str = os.environ.get("UAZAP_API_KEY", "")
    UAZAP_WEBHOOK_SECRET: str = os.environ.get("UAZAP_WEBHOOK_SECRET", "")

    UPLOAD_DIR: str = os.environ.get("UPLOAD_DIR", "/app/uploads")
    MAX_FILE_SIZE_MB: int = int(os.environ.get("MAX_FILE_SIZE_MB", "50"))

    ALLOWED_IMAGE_TYPES: list = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    ALLOWED_AUDIO_TYPES: list = ["audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav"]
    ALLOWED_VIDEO_TYPES: list = ["video/mp4", "video/webm"]
    ALLOWED_DOC_TYPES: list = ["application/pdf"]

    @property
    def CORS_ORIGINS(self) -> list:
        val = os.environ.get("CORS_ORIGINS", "http://localhost:3000")
        if not val.strip():
            return ["http://localhost:3000"]
        if val.strip().startswith("["):
            import json
            try:
                return json.loads(val)
            except Exception:
                pass
        return [x.strip() for x in val.split(",") if x.strip()]

    REMINDER_CHECK_INTERVAL: int = 60
    CAMPAIGN_CHECK_INTERVAL: int = 30
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379")

settings = Settings()