"""
app/api/v1/conversations.py
Gerenciamento de conversas - com suporte a realtime via SSE
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional, List
import asyncio
import json
from datetime import datetime

from app.core.database import get_supabase
from app.services.whatsapp_service import whatsapp_client

router = APIRouter()


@router.get("")
async def list_conversations(
    workspace_id: str,
    status: Optional[str] = None,
    ai_status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(50, le=100),
    offset: int = 0,
):
    """Lista conversas do workspace"""
    supabase = get_supabase()
    q = supabase.table("conversations").select(
        "*, contacts(name, phone, avatar_url)"
    ).eq("workspace_id", workspace_id)

    if status:    q = q.eq("status", status)
    if ai_status: q = q.eq("ai_status", ai_status)

    result = q.order("last_message_at", desc=True).range(offset, offset + limit - 1).execute()
    data = result.data or []

    # Filtro de busca client-side (Supabase free não tem full-text grátis)
    if search:
        s = search.lower()
        data = [
            c for c in data
            if s in (c.get("contacts", {}) or {}).get("name", "").lower()
            or s in (c.get("contacts", {}) or {}).get("phone", "").lower()
        ]

    # Normalizar para o frontend
    for c in data:
        contact = c.pop("contacts", {}) or {}
        c["contact_name"]   = contact.get("name")
        c["contact_phone"]  = contact.get("phone")
        c["contact_avatar"] = contact.get("avatar_url")

    return data


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    workspace_id: str,
):
    """Busca conversa com detalhes do contato"""
    supabase = get_supabase()
    result = supabase.table("conversations").select(
        "*, contacts(name, phone, email, tags, notes, avatar_url)"
    ).eq("id", conversation_id).eq("workspace_id", workspace_id).single().execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")

    data = result.data
    contact = data.pop("contacts", {}) or {}
    data.update({
        "contact_name":   contact.get("name"),
        "contact_phone":  contact.get("phone"),
        "contact_email":  contact.get("email"),
        "contact_tags":   contact.get("tags"),
        "contact_notes":  contact.get("notes"),
        "contact_avatar": contact.get("avatar_url"),
    })
    return data


@router.patch("/{conversation_id}/ai-status")
async def toggle_ai_status(
    conversation_id: str,
    workspace_id: str,
    ai_status: str,  # "active" | "paused" | "stopped"
):
    """
    Pausa ou ativa a IA em uma conversa específica.
    Quando pausada, mensagens chegam mas IA não responde.
    """
    supabase = get_supabase()
    
    result = supabase.table("conversations").update({
        "ai_status": ai_status,
        "updated_at": datetime.now().isoformat(),
    }).eq("id", conversation_id).eq("workspace_id", workspace_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return {"status": "updated", "ai_status": ai_status}


@router.post("/{conversation_id}/send")
async def send_manual_message(
    conversation_id: str,
    workspace_id: str,
    body: dict,
):
    """
    Envia mensagem manual pelo atendente (humano assume a conversa).
    Automaticamente pausa a IA por 10 minutos.
    """
    supabase = get_supabase()
    
    # Buscar conversa e contato
    conv = supabase.table("conversations").select(
        "*, contacts(phone)"
    ).eq("id", conversation_id).eq("workspace_id", workspace_id).single().execute()
    
    if not conv.data:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    phone = conv.data["contacts"]["phone"]
    content = body.get("content", "")
    msg_type = body.get("type", "text")
    media_url = body.get("media_url")
    
    # Enviar via WhatsApp
    if msg_type == "image" and media_url:
        await whatsapp_client.send_image(phone, media_url, content, workspace_id)
    elif msg_type == "document" and media_url:
        await whatsapp_client.send_document(phone, media_url, body.get("filename", "doc.pdf"), workspace_id)
    else:
        await whatsapp_client.send_text(phone, content, workspace_id)
    
    # Salvar mensagem
    msg = supabase.table("messages").insert({
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        "contact_id": conv.data["contact_id"],
        "direction": "outbound",
        "type": msg_type,
        "content": content,
        "media_url": media_url,
        "is_ai": False,
        "status": "sent",
    }).execute()
    
    # Atualizar preview + pausar IA (atendente assumiu)
    supabase.table("conversations").update({
        "last_message": content,
        "last_message_at": datetime.now().isoformat(),
        "ai_status": "paused",  # IA pausa quando humano responde
    }).eq("id", conversation_id).execute()
    
    return msg.data[0] if msg.data else {}


@router.get("/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    workspace_id: str,
    limit: int = Query(50, le=100),
    before: Optional[str] = None,
):
    """Busca mensagens de uma conversa"""
    supabase = get_supabase()
    q = supabase.table("messages").select("*").eq(
        "conversation_id", conversation_id
    ).eq("workspace_id", workspace_id)

    if before:
        q = q.lt("created_at", before)

    result = q.order("created_at", desc=True).limit(limit).execute()
    messages = list(reversed(result.data or []))
    return messages


@router.get("/{conversation_id}/stream")
async def stream_conversation(
    conversation_id: str,
    workspace_id: str,
):
    """
    Server-Sent Events para atualização em tempo real da conversa
    O frontend se inscreve neste endpoint para receber novas mensagens
    """
    async def event_generator():
        supabase = get_supabase()
        last_check = datetime.now().isoformat()
        
        yield f"data: {json.dumps({'type': 'connected', 'conversation_id': conversation_id})}\n\n"
        
        while True:
            await asyncio.sleep(2)  # poll a cada 2 segundos
            
            try:
                new_msgs = supabase.table("messages").select("*").eq(
                    "conversation_id", conversation_id
                ).gt("created_at", last_check).order("created_at").execute()
                
                if new_msgs.data:
                    for msg in new_msgs.data:
                        yield f"data: {json.dumps({'type': 'message', 'data': msg})}\n\n"
                    last_check = new_msgs.data[-1]["created_at"]
                
                # Heartbeat
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                break
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.patch("/{conversation_id}/read")
async def mark_as_read(
    conversation_id: str,
    workspace_id: str,
):
    """Marca todas as mensagens da conversa como lidas"""
    supabase = get_supabase()
    from datetime import datetime as dt
    
    supabase.table("messages").update({
        "read_at": dt.now().isoformat()
    }).eq("conversation_id", conversation_id).is_("read_at", "null").eq(
        "direction", "inbound"
    ).execute()
    
    supabase.table("conversations").update({"unread_count": 0}).eq(
        "id", conversation_id
    ).execute()
    
    return {"status": "ok"}


@router.post("/{conversation_id}/reactivate-ai")
async def reactivate_ai(
    conversation_id: str,
    workspace_id: str,
    message: str = "",
):
    """Reativa IA após inatividade — chamado pelo scheduler ou flow"""
    supabase = get_supabase()
    supabase.table("conversations").update({
        "ai_status": "active",
        "updated_at": __import__('datetime').datetime.now().isoformat(),
    }).eq("id", conversation_id).eq("workspace_id", workspace_id).execute()

    # Enviar mensagem de retorno se configurada
    if message:
        from app.services.whatsapp_service import whatsapp_client
        conv = supabase.table("conversations").select(
            "contact_id, contacts(phone)"
        ).eq("id", conversation_id).single().execute()
        if conv.data:
            phone = (conv.data.get("contacts") or {}).get("phone", "")
            if phone:
                await whatsapp_client.send_text(phone, message, workspace_id)

    return {"status": "reactivated", "conversation_id": conversation_id}
