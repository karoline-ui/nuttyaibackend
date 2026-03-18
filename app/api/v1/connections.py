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

async def _register_webhook(workspace_id: str, connection_id: str = None):
    """
    Registra a URL de webhook no UazAP E salva no config da connection.
    Assim fica tudo na tabela connections, filtrado por workspace.
    """
    try:
        supabase = get_supabase()
        webhook_url = f"{BACKEND_URL}/api/v1/webhooks/uazap/{workspace_id}"

        # Registra no UazAP
        await whatsapp_client.set_webhook(workspace_id, webhook_url)
        print(f"✅ Webhook registrado no UazAP: {webhook_url}")

        # Salva webhook_url no config da connection (na tabela connections)
        if connection_id:
            conn = supabase.table("connections").select("config").eq("id", connection_id).single().execute()
            current_config = (conn.data or {}).get("config", {}) or {}
            current_config["webhook_url"] = webhook_url
            current_config["webhook_registered"] = True
            supabase.table("connections").update({
                "config": current_config,
                "is_active": True,
            }).eq("id", connection_id).execute()
            print(f"✅ webhook_url salvo no config da connection {connection_id}")
        else:
            # Busca a connection uazap do workspace e atualiza
            conn = supabase.table("connections").select("id, config").eq(
                "workspace_id", workspace_id
            ).eq("type", "uazap").limit(1).execute()
            if conn.data:
                cid = conn.data[0]["id"]
                current_config = conn.data[0].get("config", {}) or {}
                current_config["webhook_url"] = webhook_url
                current_config["webhook_registered"] = True
                supabase.table("connections").update({
                    "config": current_config,
                    "is_active": True,
                }).eq("id", cid).execute()
                print(f"✅ webhook_url salvo no config da connection {cid}")
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
    conn = result.data[0] if result.data else {}
    # Registra webhook e salva no config da connection
    if conn.get("id") and body.get("type") == "uazap":
        await _register_webhook(workspace_id, conn["id"])
    return conn

@router.patch("/{connection_id}")
async def update_connection(connection_id: str, workspace_id: str, body: dict):
    supabase = get_supabase()
    body["updated_at"] = datetime.now().isoformat()
    result = supabase.table("connections").update(body).eq(
        "id", connection_id
    ).eq("workspace_id", workspace_id).execute()
    # Re-registra webhook e salva no config
    await _register_webhook(workspace_id, connection_id)
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