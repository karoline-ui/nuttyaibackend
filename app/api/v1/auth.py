"""
app/api/v1/auth.py — Auth próprio com JWT (sem Supabase Auth)
"""
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from app.core.database import get_supabase
from app.core.config import settings
import bcrypt
import jwt
from datetime import datetime, timedelta
from typing import Optional

router = APIRouter()

class LoginRequest(BaseModel):
    email: str
    password: str

def create_token(user_id: str, email: str, role: str, workspace_id: Optional[str]) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "workspace_id": workspace_id,
        "exp": datetime.utcnow() + timedelta(days=7),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")

def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

@router.post("/login")
async def login(body: LoginRequest):
    supabase = get_supabase()

    # Buscar usuário
    result = supabase.table("app_users").select("*").eq(
        "email", body.email.lower().strip()
    ).eq("is_active", True).single().execute()

    if not result.data:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    user = result.data

    # Verificar senha
    try:
        valid = bcrypt.checkpw(
            body.password.encode("utf-8"),
            user["password_hash"].encode("utf-8")
        )
    except Exception:
        valid = False

    if not valid:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    # Atualizar last_login
    supabase.table("app_users").update({
        "last_login_at": datetime.now().isoformat()
    }).eq("id", user["id"]).execute()

    token = create_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        workspace_id=user.get("workspace_id"),
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "workspace_id": user.get("workspace_id"),
        }
    }

@router.get("/me")
async def get_me(authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "").replace("bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Token não fornecido")

    payload = verify_token(token)
    supabase = get_supabase()

    result = supabase.table("app_users").select(
        "id, email, full_name, role, workspace_id, is_active"
    ).eq("id", payload["sub"]).single().execute()

    if not result.data:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")

    return result.data

@router.get("/users")
async def list_users(authorization: str = Header(default="")):
    """Lista todos os usuários — apenas admin"""
    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado")
    supabase = get_supabase()
    result = supabase.table("app_users").select(
        "id, email, full_name, role, workspace_id, is_active, last_login_at, created_at"
    ).order("created_at", desc=True).execute()
    return result.data or []


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: dict, authorization: str = Header(default="")):
    """Atualiza usuário — apenas admin"""
    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado")
    supabase = get_supabase()
    allowed = {k: v for k, v in body.items() if k in ["full_name", "role", "workspace_id", "is_active"]}
    result = supabase.table("app_users").update(allowed).eq("id", user_id).execute()
    return result.data[0] if result.data else {}


@router.post("/create-user")
async def create_user(body: dict, authorization: str = Header(default="")):
    """Cria usuário — apenas admin pode chamar"""
    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)

    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Apenas admin pode criar usuários")

    supabase = get_supabase()

    email = body.get("email", "").lower().strip()
    password = body.get("password", "")

    if not email:
        raise HTTPException(status_code=400, detail="Email é obrigatório")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Senha deve ter mínimo 6 caracteres")

    # Verificar se email já existe
    existing = supabase.table("app_users").select("id, email").eq("email", email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail=f"Email '{email}' já está em uso")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    result = supabase.table("app_users").insert({
        "email": email,
        "password_hash": hashed,
        "full_name": body.get("full_name", ""),
        "role": body.get("role", "client"),
        "workspace_id": body.get("workspace_id"),
    }).execute()

    if not result.data:
        raise HTTPException(status_code=400, detail="Erro ao criar usuário")

    user = result.data[0]
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "workspace_id": user.get("workspace_id"),
    }

@router.post("/change-password")
async def change_password(body: dict, authorization: str = Header(default="")):
    token = authorization.replace("Bearer ", "")
    payload = verify_token(token)

    new_password = body.get("new_password", "")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Senha deve ter mínimo 6 caracteres")

    hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    supabase = get_supabase()
    supabase.table("app_users").update({
        "password_hash": hashed
    }).eq("id", payload["sub"]).execute()

    return {"status": "ok", "message": "Senha alterada com sucesso"}