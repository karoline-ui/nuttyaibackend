"""
app/api/v1/webhooks.py
"""
from fastapi import APIRouter, Request
import logging
import traceback

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/uazap/{workspace_id}")
async def receive_uazap_webhook(workspace_id: str, request: Request):
    try:
        payload = await request.json()
    except Exception as e:
        print(f"❌ JSON parse error: {e}")
        return {"status": "error"}

    event   = payload.get("event", "")
    data    = payload.get("data", {})
    key     = data.get("key", {})
    msg     = data.get("message", {})
    from_me = key.get("fromMe", False)
    jid     = key.get("remoteJid", "")

    import json
    print(f"📨 WEBHOOK COMPLETO: {json.dumps(payload)[:2000]}")
    print(f"📨 WEBHOOK ws={workspace_id} event={event!r} fromMe={from_me} jid={jid} msg_keys={list(msg.keys())}")

    # Ignorar mensagens do próprio bot
    if from_me:
        return {"status": "ok", "skipped": "own_message"}

    # Ignorar eventos de status/conexão
    skip_events = {"connection.update", "qrcode.updated", "presence.update", "message_ack", "call", "group_update"}
    if event in skip_events:
        return {"status": "ok", "skipped": event}

    # Processar DIRETO — sem background task
    try:
        from app.services.whatsapp_service import process_incoming_webhook
        print(f"⚙️ Chamando process_incoming_webhook...")
        await process_incoming_webhook(payload=payload, workspace_id=workspace_id)
        print(f"✅ process_incoming_webhook concluído")
    except Exception as e:
        print(f"❌ ERRO process_incoming_webhook: {e}")
        print(traceback.format_exc())

    return {"status": "ok"}


@router.post("/custom/{workspace_id}/{connection_id}")
async def receive_custom_webhook(workspace_id: str, connection_id: str, request: Request):
    payload = await request.json()
    print(f"📨 Custom webhook ws={workspace_id} conn={connection_id}")
    return {"status": "received"}