"""
app/api/v1/connections.py
"""
from fastapi import APIRouter, HTTPException
from app.core.database import get_supabase
from app.services.whatsapp_service import whatsapp_client
from app.core.config import settings
from datetime import datetime

router = APIRouter()

BACKEND_URL = "https://nuttyaibackend-897373535500.southamerica-east1.run.app"

async def _register_webhook(workspace_id: str):
    """Registra a URL de webhook no UazAP para este workspace"""
    try:
        webhook_url = f"{BACKEND_URL}/api/v1/webhooks/uazap/{workspace_id}"
        await whatsapp_client.set_webhook(workspace_id, webhook_url)
        print(f"✅ Webhook registrado: {webhook_url}")
    except Exception as e:
        print(f"⚠️ Erro ao registrar webhook: {e}")

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
    # Registra webhook automaticamente
    await _register_webhook(workspace_id)
    return result.data[0] if result.data else {}

@router.patch("/{connection_id}")
async def update_connection(connection_id: str, workspace_id: str, body: dict):
    supabase = get_supabase()
    body["updated_at"] = datetime.now().isoformat()
    result = supabase.table("connections").update(body).eq(
        "id", connection_id
    ).eq("workspace_id", workspace_id).execute()
    # Re-registra webhook ao atualizar
    await _register_webhook(workspace_id)
    return result.data[0] if result.data else {}

@router.delete("/{connection_id}")
async def delete_connection(connection_id: str, workspace_id: str):
    supabase = get_supabase()
    supabase.table("connections").delete().eq("id", connection_id).eq(
        "workspace_id", workspace_id
    ).execute()
    return {"status": "deleted"}

@router.post("/{connection_id}/register-webhook")
async def register_webhook(connection_id: str, workspace_id: str):
    """Força o re-registro do webhook no UazAP"""
    await _register_webhook(workspace_id)
    return {"status": "ok", "webhook_url": f"{BACKEND_URL}/api/v1/webhooks/uazap/{workspace_id}"}

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
            # Aproveita e re-registra webhook
            if status == "ok":
                await _register_webhook(workspace_id)
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