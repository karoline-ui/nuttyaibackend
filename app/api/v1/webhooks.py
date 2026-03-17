"""
app/api/v1/webhooks.py
Recebe webhooks do UazAP e outros serviços
"""
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, Header
from typing import Optional
import json

from app.core.database import get_supabase
from app.services.whatsapp_service import process_incoming_webhook, whatsapp_client

router = APIRouter()


@router.post("/uazap/{workspace_id}")
async def receive_uazap_webhook(
    workspace_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature: Optional[str] = Header(None),
):
    """
    Endpoint de webhook para o UazAP.
    Configure este URL no painel do UazAP:
    https://seu-dominio/api/v1/webhooks/uazap/{workspace_id}
    """
    body = await request.body()
    
    # Verificar assinatura (se configurada)
    # if x_hub_signature:
    #     if not whatsapp_client.verify_webhook(body.decode(), x_hub_signature):
    #         raise HTTPException(status_code=401, detail="Invalid signature")
    
    payload = await request.json()
    
    # Salvar webhook raw
    supabase = get_supabase()
    supabase.table("webhooks").insert({
        "workspace_id": workspace_id,
        "source": "uazap",
        "payload": payload,
        "processed": False,
    }).execute()
    
    # Ignorar mensagens enviadas pelo próprio bot
    msg_data = payload.get("data", {})
    key = msg_data.get("key", {})
    if key.get("fromMe", False):
        return {"status": "ok", "message": "own message ignored"}
    
    # Processar em background
    background_tasks.add_task(
        process_incoming_webhook,
        payload=payload,
        workspace_id=workspace_id
    )
    
    return {"status": "ok"}


@router.post("/custom/{workspace_id}/{connection_id}")
async def receive_custom_webhook(
    workspace_id: str,
    connection_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Webhook genérico para integrações customizadas"""
    payload = await request.json()
    
    supabase = get_supabase()
    supabase.table("webhooks").insert({
        "workspace_id": workspace_id,
        "source": f"custom:{connection_id}",
        "payload": payload,
        "processed": False,
    }).execute()
    
    # Aqui você pode triggar um flow
    # background_tasks.add_task(trigger_flow_by_webhook, workspace_id, connection_id, payload)
    
    return {"status": "received"}
