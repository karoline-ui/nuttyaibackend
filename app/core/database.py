"""
app/core/database.py - Conexão Supabase
"""
from supabase import create_client, Client
from app.core.config import settings
from typing import Optional

# Cliente Supabase (para auth e operações)
supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_KEY
)

# Pool asyncpg para queries diretas (opcional - só usa se DATABASE_URL estiver configurada)
_pool = None

async def init_db():
    global _pool
    db_url = settings.DATABASE_URL or ""

    # Pular se URL inválida, vazia ou ainda tem placeholder
    skip_reasons = ["[YOUR-PASSWORD]", "SEU_PROJETO", "SENHA", ""]
    if not db_url or any(r in db_url for r in skip_reasons):
        print("⚠️  DATABASE_URL não configurada — modo Supabase client only")
        return

    try:
        import asyncpg
        _pool = await asyncpg.create_pool(
            db_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        print("✅ Database pool initialized")
    except Exception as e:
        print(f"⚠️  asyncpg desativado ({e}) — modo Supabase client only")
        _pool = None

async def get_pool():
    return _pool

async def get_db():
    """Dependency para FastAPI - retorna conexão do pool ou None"""
    if _pool is None:
        yield None
        return
    async with _pool.acquire() as conn:
        yield conn

def get_supabase() -> Client:
    return supabase