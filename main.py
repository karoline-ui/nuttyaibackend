"""
NUTTY.AI SAAS — Backend FastAPI
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.database import init_db
from app.api.v1 import router as api_v1_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    from app.services.scheduler import start_scheduler
    await start_scheduler()
    yield
    from app.services.scheduler import stop_scheduler
    await stop_scheduler()

app = FastAPI(
    title="Nutty.AI API",
    version="1.0.0",
    lifespan=lifespan,
    # Desabilita docs em produção
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)

app.include_router(api_v1_router, prefix="/api/v1")

@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
