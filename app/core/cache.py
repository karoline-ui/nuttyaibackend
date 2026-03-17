"""
Cache em memória simples para reduzir chamadas ao Supabase.
TTL padrão: 30 segundos. Use para dados que mudam pouco.
"""
import time
from typing import Any, Optional
from functools import wraps

_cache: dict[str, tuple[Any, float]] = {}

def get(key: str) -> Optional[Any]:
    if key in _cache:
        value, expires_at = _cache[key]
        if time.time() < expires_at:
            return value
        del _cache[key]
    return None

def set(key: str, value: Any, ttl: int = 30) -> None:
    _cache[key] = (value, time.time() + ttl)

def delete(key: str) -> None:
    _cache.pop(key, None)

def delete_prefix(prefix: str) -> None:
    keys = [k for k in _cache if k.startswith(prefix)]
    for k in keys:
        del _cache[k]

def cached(ttl: int = 30, key_prefix: str = ""):
    """Decorator para cachear resultados de funções async"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix or func.__name__}:{str(args)}:{str(sorted(kwargs.items()))}"
            cached_val = get(cache_key)
            if cached_val is not None:
                return cached_val
            result = await func(*args, **kwargs)
            set(cache_key, result, ttl)
            return result
        return wrapper
    return decorator
