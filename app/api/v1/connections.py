"""
app/api/v1/connections.py
"""
from fastapi import APIRouter, HTTPException
from app.core.database import get_supabase
from app.services.whatsapp_service import whatsapp_client
from datetime import datetime
router = APIRouter()

@router.get("")
async def list_connections(workspace_id: str):
    supabase = get_supabase()
    result = supabase.table("connections").select("*").eq(
        "workspace_id", workspace_id
    ).order("created_at", desc=True).execute()
    return result.data

@router.post("")
async def create_connection(workspace_id: str, body: dict):
    supabase = get_supabase()
    result = supabase.table("connections").insert({
        "workspace_id": workspace_id, **body
    }).execute()
    return result.data[0] if result.data else {}

@router.patch("/{connection_id}")
async def update_connection(connection_id: str, workspace_id: str, body: dict):
    supabase = get_supabase()
    body["updated_at"] = datetime.now().isoformat()
    result = supabase.table("connections").update(body).eq(
        "id", connection_id
    ).eq("workspace_id", workspace_id).execute()
    return result.data[0] if result.data else {}

@router.delete("/{connection_id}")
async def delete_connection(connection_id: str, workspace_id: str):
    supabase = get_supabase()
    supabase.table("connections").delete().eq("id", connection_id).eq(
        "workspace_id", workspace_id
    ).execute()
    return {"status": "deleted"}

@router.post("/{connection_id}/test")
async def test_connection(connection_id: str, workspace_id: str):
    supabase = get_supabase()
    conn = supabase.table("connections").select("*").eq(
        "id", connection_id
    ).eq("workspace_id", workspace_id).single().execute()
    if not conn.data:
        raise HTTPException(status_code=404, detail="Connection not found")

    status = "ok"
    msg = "Conexão testada"
    try:
        if conn.data["type"] == "uazap":
            result = await whatsapp_client.get_status(workspace_id)
            status = "ok" if result.get("connected") else "error"
            msg = "WhatsApp conectado" if status == "ok" else "WhatsApp desconectado"
    except Exception as e:
        status = "error"
        msg = str(e)

    supabase.table("connections").update({
        "last_tested_at": datetime.now().isoformat(),
        "test_status": status,
        "test_message": msg,
    }).eq("id", connection_id).execute()

    if status == "error":
        raise HTTPException(status_code=400, detail=msg)
    return {"status": status, "message": msg}