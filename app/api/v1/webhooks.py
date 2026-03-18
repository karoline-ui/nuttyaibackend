"""
app/api/v1/webhooks.py
"""
from fastapi import APIRouter, Request, BackgroundTasks, Header
from typing import Optional
import logging
import json

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/uazap/{workspace_id}")
async def receive_uazap_webhook(
    workspace_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    try:
        payload = await request.json()
    except Exception as e:
        logger.error(f"❌ Webhook JSON parse error: {e}")
        return {"status": "error", "detail": str(e)}

    # Log imediato do payload
    event   = payload.get("event", "")
    data    = payload.get("data", {})
    key     = data.get("key", {})
    msg     = data.get("message", {})
    from_me = key.get("fromMe", False)
    jid     = key.get("remoteJid", "")

    logger.info(f"📨 WEBHOOK workspace={workspace_id} event={event!r} fromMe={from_me} jid={jid} msg_keys={list(msg.keys())}")
    print(f"📨 WEBHOOK workspace={workspace_id} event={event!r} fromMe={from_me} jid={jid} msg_keys={list(msg.keys())}")

    # Ignorar mensagens do próprio bot
    if from_me:
        print(f"⏭️ Ignorando fromMe")
        return {"status": "ok", "skipped": "own_message"}

    # Ignorar eventos de conexão/status
    skip_events = {"connection.update", "qrcode.updated", "presence.update",
                   "message_ack", "call", "group_update"}
    if event in skip_events:
        print(f"⏭️ Ignorando evento {event!r}")
        return {"status": "ok", "skipped": event}

    # Tenta salvar no banco (não crítico se falhar)
    try:
        from app.core.database import get_supabase
        supabase = get_supabase()
        supabase.table("webhooks").insert({
            "workspace_id": workspace_id,
            "source": "uazap",
            "payload": payload,
            "processed": False,
        }).execute()
    except Exception as e:
        print(f"⚠️ Não salvou webhook no banco (ok): {e}")

    # Processa direto (não background) para capturar erros
    print(f"🚀 Processando mensagem direto...")
    try:
        from app.services.whatsapp_service import process_incoming_webhook
        await process_incoming_webhook(payload=payload, workspace_id=workspace_id)
        print(f"✅ Webhook processado com sucesso workspace={workspace_id}")
    except Exception as e:
        import traceback
        print(f"❌ Erro ao processar webhook: {e}")
        print(traceback.format_exc())

    return {"status": "ok"}


@router.post("/custom/{workspace_id}/{connection_id}")
async def receive_custom_webhook(
    workspace_id: str,
    connection_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    payload = await request.json()
    print(f"📨 Custom webhook workspace={workspace_id} connection={connection_id}")
    return {"status": "received"}
