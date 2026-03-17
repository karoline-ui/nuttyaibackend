"""
app/api/v1/workspaces.py
"""
from fastapi import APIRouter, HTTPException
from app.core.database import get_supabase
from app.core.cache import get as cache_get, set as cache_set, delete_prefix
from datetime import datetime

router = APIRouter()

@router.get("")
async def list_workspaces():
    supabase = get_supabase()
    result = supabase.table("workspaces").select("*").order("created_at", desc=True).execute()
    return result.data

@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str):
    supabase = get_supabase()
    result = supabase.table("workspaces").select("*").eq("id", workspace_id).single().execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return result.data

@router.patch("/{workspace_id}")
async def update_workspace(workspace_id: str, body: dict):
    import logging
    supabase = get_supabase()
    # Campos permitidos para atualização
    ALLOWED = {
        'name', 'ai_persona', 'ai_instructions', 'ai_status',
        'business_hours', 'phone_number', 'timezone', 'primary_color',
        'segment', 'niche', 'settings', 'gemini_api_key', 'logo_url',
    }
    safe_body = {k: v for k, v in body.items() if k in ALLOWED}
    safe_body["updated_at"] = datetime.now().isoformat()
    logging.info(f"[PATCH workspace {workspace_id}] fields: {list(safe_body.keys())}")
    if 'ai_instructions' in safe_body:
        logging.info(f"  ai_instructions length: {len(safe_body['ai_instructions'] or '')}")
    result = supabase.table("workspaces").update(safe_body).eq("id", workspace_id).execute()
    if not result.data:
        logging.warning(f"  No data returned — workspace may not exist or RLS blocked")
    return result.data[0] if result.data else {}

@router.post("")
async def create_workspace(body: dict):
    import re, time
    supabase = get_supabase()
    
    # Garantir slug único
    slug = body.get("slug", "")
    if not slug:
        slug = re.sub(r'[^a-z0-9-]', '', body.get("name", "workspace").lower().replace(" ", "-"))
    
    # Verificar se slug já existe e adicionar sufixo
    existing = supabase.table("workspaces").select("slug").eq("slug", slug).execute()
    if existing.data:
        slug = f"{slug}-{int(time.time()) % 10000}"
    
    body["slug"] = slug
    result = supabase.table("workspaces").insert(body).execute()
    return result.data[0] if result.data else {}

@router.delete("/{workspace_id}")
async def delete_workspace(workspace_id: str):
    """
    Exclui o workspace e todos os dados relacionados.
    Ordem: messages → conversations → appointments → campaigns → flows
           → knowledge_base → contacts → connections → media → workspace
    """
    supabase = get_supabase()
    tables_to_clean = [
        "messages", "conversations", "appointments",
        "campaigns", "flows", "knowledge_base",
        "contacts", "connections", "media_files",
    ]
    for table in tables_to_clean:
        try:
            supabase.table(table).delete().eq("workspace_id", workspace_id).execute()
        except Exception:
            pass  # tabela pode não existir ou já estar vazia

    # Desativar usuários do workspace
    try:
        supabase.table("app_users").update({"is_active": False}).eq("workspace_id", workspace_id).execute()
    except Exception:
        pass

    # Excluir workspace
    result = supabase.table("workspaces").delete().eq("id", workspace_id).execute()
    return {"status": "deleted", "workspace_id": workspace_id}
