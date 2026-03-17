"""
app/core/config.py - Configurações centrais
"""
from pydantic_settings import BaseSettings
from typing import List
import os

class Settings(BaseSettings):
    BACKEND_URL: str = ""  # Ex: https://nutty-backend.run.app
    # App
    APP_NAME: str = "Nutty.AI"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "nutty-secret-change-in-production"
    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""  # service_role key para operações admin
    DATABASE_URL: str = ""          # postgresql://... direto
    
    # Gemini AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_VISION_MODEL: str = "gemini-2.5-flash"
    
    # UazAP (WhatsApp)
    UAZAP_BASE_URL: str = "https://api.uazap.com"  # ajuste conforme doc
    UAZAP_API_KEY: str = ""
    UAZAP_WEBHOOK_SECRET: str = ""
    
    # Storage (local)
    UPLOAD_DIR: str = "/app/uploads"
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_IMAGE_TYPES: List[str] = ["image/jpeg","image/png","image/webp","image/gif"]
    ALLOWED_AUDIO_TYPES: List[str] = ["audio/ogg","audio/mp4","audio/mpeg","audio/wav"]
    ALLOWED_VIDEO_TYPES: List[str] = ["video/mp4","video/webm"]
    ALLOWED_DOC_TYPES: List[str] = ["application/pdf"]
    
    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000","http://localhost:3001","https://localhost:3000"]
    
    # Scheduler
    REMINDER_CHECK_INTERVAL: int = 60   # segundos
    CAMPAIGN_CHECK_INTERVAL: int = 30
    
    # Redis (opcional, para queue)
    REDIS_URL: str = "redis://localhost:6379"
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # ignora variáveis não declaradas (ex: NEXT_PUBLIC_*)

settings = Settings()
