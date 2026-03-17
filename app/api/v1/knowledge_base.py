"""
app/api/v1/knowledge_base.py
"""
from fastapi import APIRouter, HTTPException
from app.core.database import get_supabase
from datetime import datetime
router = APIRouter()

@router.get("")
async def list_knowledge(workspace_id: str):
    supabase = get_supabase()
    result = supabase.table("knowledge_base").select("*").eq(
        "workspace_id", workspace_id
    ).order("created_at", desc=True).execute()
    return result.data

@router.post("")
async def create_knowledge(workspace_id: str, body: dict):
    supabase = get_supabase()
    result = supabase.table("knowledge_base").insert({
        "workspace_id": workspace_id, **body
    }).execute()
    return result.data[0] if result.data else {}

@router.patch("/{item_id}")
async def update_knowledge(item_id: str, workspace_id: str, body: dict):
    supabase = get_supabase()
    body["updated_at"] = datetime.now().isoformat()
    result = supabase.table("knowledge_base").update(body).eq(
        "id", item_id
    ).eq("workspace_id", workspace_id).execute()
    return result.data[0] if result.data else {}

@router.delete("/{item_id}")
async def delete_knowledge(item_id: str, workspace_id: str):
    supabase = get_supabase()
    supabase.table("knowledge_base").delete().eq("id", item_id).eq(
        "workspace_id", workspace_id
    ).execute()
    return {"status": "deleted"}
