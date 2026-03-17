"""
app/core/config.py - Configurações centrais
"""
from pydantic_settings import BaseSettings
from pydantic import validator
from typing import List
import os
import json

def _parse_list(v, default):
    """Converte string de env var para lista, com fallback seguro."""
    if isinstance(v, list):
        return v if v else default
    if not v or not v.strip():
        return default
    v = v.strip()
    if v.startswith('['):
        try:
            result = json.loads(v)
            return result if result else default
        except Exception:
            pass
    return [i.strip() for i in v.split(',') if i.strip()] or default

class Settings(BaseSettings):
    # App
    APP_NAME: str = "Nutty.AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "nutty-secret-change-in-production"

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""
    DATABASE_URL: str = ""

    # Gemini AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_VISION_MODEL: str = "gemini-2.5-flash"

    # UazAP (WhatsApp)
    UAZAP_BASE_URL: str = "https://api.uazap.com"
    UAZAP_API_KEY: str = ""
    UAZAP_WEBHOOK_SECRET: str = ""

    # Storage
    UPLOAD_DIR: str = "/app/uploads"
    MAX_FILE_SIZE_MB: int = 50

    # Tipos permitidos — armazenados como string, convertidos pelo validator
    ALLOWED_IMAGE_TYPES: List[str] = ["image/jpeg","image/png","image/webp","image/gif"]
    ALLOWED_AUDIO_TYPES: List[str] = ["audio/ogg","audio/mp4","audio/mpeg","audio/wav"]
    ALLOWED_VIDEO_TYPES: List[str] = ["video/mp4","video/webm"]
    ALLOWED_DOC_TYPES: List[str] = ["application/pdf"]

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000","http://localhost:3001","https://localhost:3000"]

    @validator('CORS_ORIGINS', pre=True)
    def parse_cors(cls, v):
        return _parse_list(v, ["http://localhost:3000"])

    @validator('ALLOWED_IMAGE_TYPES', pre=True)
    def parse_image_types(cls, v):
        return _parse_list(v, ["image/jpeg","image/png","image/webp","image/gif"])

    @validator('ALLOWED_AUDIO_TYPES', pre=True)
    def parse_audio_types(cls, v):
        return _parse_list(v, ["audio/ogg","audio/mp4","audio/mpeg","audio/wav"])

    @validator('ALLOWED_VIDEO_TYPES', pre=True)
    def parse_video_types(cls, v):
        return _parse_list(v, ["video/mp4","video/webm"])

    @validator('ALLOWED_DOC_TYPES', pre=True)
    def parse_doc_types(cls, v):
        return _parse_list(v, ["application/pdf"])

    # Scheduler
    REMINDER_CHECK_INTERVAL: int = 60
    CAMPAIGN_CHECK_INTERVAL: int = 30

    # Redis (opcional)
    REDIS_URL: str = "redis://localhost:6379"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

settings = Settings()