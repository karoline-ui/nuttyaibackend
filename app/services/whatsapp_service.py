"""
app/services/whatsapp_service.py
Serviço UazAP (WhatsApp API v2) — payloads corretos conforme documentação
"""
import httpx
import asyncio
from typing import Optional
from app.core.config import settings
from app.core.database import get_supabase


class WhatsAppService:

    async def _get_connection(self, workspace_id: str) -> dict:
        """Busca a conexão UazAP ativa do workspace — retorna {url, api_key}"""
        try:
            supabase = get_supabase()
            result = supabase.table("connections").select("config, is_active").eq(
                "workspace_id", workspace_id
            ).eq("type", "uazap").limit(1).execute()
            if result.data:
                config = result.data[0].get("config", {}) or {}
                return {
                    "url": config.get("endpoint") or config.get("url") or settings.UAZAP_BASE_URL,
                    "api_key": config.get("api_key") or settings.UAZAP_API_KEY,
                }
        except Exception as e:
            print(f"⚠️ _get_connection error: {e}")
        return {
            "url": settings.UAZAP_BASE_URL,
            "api_key": settings.UAZAP_API_KEY,
        }

    async def _post(self, endpoint: str, payload: dict, workspace_id: str = None) -> dict:
        """Helper: faz POST autenticado na UazAP usando config do workspace"""
        try:
            conn = await self._get_connection(workspace_id) if workspace_id else {
                "url": settings.UAZAP_BASE_URL,
                "api_key": settings.UAZAP_API_KEY,
            }
            print(f"📤 POST {conn['url']}{endpoint}")
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{conn['url']}{endpoint}",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "token": conn["api_key"],
                    }
                )
                print(f"📤 Response {r.status_code}: {r.text[:200]}")
                return r.json() if r.content else {"status": r.status_code}
        except Exception as e:
            print(f"❌ _post error: {e}")
            return {"error": str(e)}

    # ── TEXTO ───────────────────────────────────────────────────────────────
    async def send_text(self, phone: str, message: str, workspace_id: str) -> dict:
        """Envia mensagem de texto simples"""
        return await self._post(f"/message/sendText", {
            "number": phone,
            "text": message,
        }, workspace_id=workspace_id)

    # ── IMAGEM ──────────────────────────────────────────────────────────────
    async def send_image(self, phone: str, url: str, caption: str, workspace_id: str) -> dict:
        return await self._post("/message/sendMedia", {
            "number": phone,
            "mediatype": "image",
            "mimetype": "image/jpeg",
            "caption": caption,
            "media": url,
            "fileName": "image.jpg",
        }, workspace_id=workspace_id)

    # ── ÁUDIO ───────────────────────────────────────────────────────────────
    async def send_audio(self, phone: str, url: str, workspace_id: str) -> dict:
        return await self._post(f"/message/sendWhatsAppAudio", {
            "number": phone,
            "audio": url,
        }, workspace_id=workspace_id)

    # ── DOCUMENTO ───────────────────────────────────────────────────────────
    async def send_document(self, phone: str, url: str, filename: str, workspace_id: str) -> dict:
        return await self._post(f"/message/sendMedia", {
            "number": phone,
            "mediatype": "document",
            "mimetype": "application/pdf",
            "caption": filename,
            "media": url,
            "fileName": filename,
        }, workspace_id=workspace_id)

    # ── BOTÕES RÁPIDOS (até 3) ───────────────────────────────────────────────
    async def send_buttons(self, phone: str, message: str, buttons: list, workspace_id: str) -> dict:
        """
        Envia mensagem com botões interativos (reply buttons).
        Payload UazAP v2 / Evolution API padrão.
        """
        return await self._post(f"/message/sendButtons", {
            "number": phone,
            "title": "",
            "description": message,
            "footer": "",
            "buttons": [
                {"type": "reply", "displayText": btn, "id": f"btn_{i}"}
                for i, btn in enumerate(buttons[:3])
            ],
        }, workspace_id=workspace_id)

    # ── LISTA INTERATIVA ────────────────────────────────────────────────────
    async def send_list(self, phone: str, message: str, title: str, items: list, workspace_id: str) -> dict:
        """
        Envia lista interativa nativa do WhatsApp.
        Agrupa tudo numa seção única.
        """
        return await self._post(f"/message/sendList", {
            "number": phone,
            "title": title,
            "description": message,
            "buttonText": "Ver opções",
            "footerText": "",
            "sections": [{
                "title": title,
                "rows": [
                    {"title": item, "description": "", "rowId": f"row_{i}"}
                    for i, item in enumerate(items[:10])
                ]
            }]
        }, workspace_id=workspace_id)

    # ── LOCALIZAÇÃO ─────────────────────────────────────────────────────────
    async def send_location(self, phone: str, lat: float, lng: float, name: str, address: str, workspace_id: str) -> dict:
        return await self._post(f"/message/sendLocation", {
            "number": phone,
            "name": name,
            "address": address,
            "latitude": lat,
            "longitude": lng,
        }, workspace_id=workspace_id)

    # ── DISPARO EM MASSA ────────────────────────────────────────────────────
    async def send_bulk_with_delay(
        self,
        contacts: list,
        message: str,
        workspace_id: str,
        delay_ms: int = 3500,
    ) -> dict:
        """Envia mensagem para múltiplos contatos com delay anti-ban"""
        sent, failed = 0, 0
        for contact in contacts:
            phone = contact.get("phone", "")
            if not phone:
                continue
            personal = message.replace("{{contact.name}}", contact.get("name", ""))
            result = await self.send_text(phone, personal, workspace_id)
            if result.get("error"):
                failed += 1
            else:
                sent += 1
            await asyncio.sleep(delay_ms / 1000)
        return {"sent": sent, "failed": failed, "total": len(contacts)}

    # ── WEBHOOK: CONFIGURAR NA UAZAP ────────────────────────────────────────
    async def set_webhook(self, workspace_id: str, webhook_url: str) -> dict:
        """Registra webhook no UazAP para o workspace — busca token da instância no banco"""
        try:
            supabase = get_supabase()
            # Busca a conexão do workspace para pegar o token da instância
            result = supabase.table("connections").select("*").eq(
                "workspace_id", workspace_id
            ).eq("type", "uazap").limit(1).execute()

            if not result.data:
                return {"error": "No UazAP connection found"}

            conn = result.data[0]
            config = conn.get("config", {})
            instance_token = config.get("api_key") or config.get("token") or settings.UAZAP_API_KEY
            instance_url = config.get("url") or settings.UAZAP_BASE_URL

            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{instance_url}/webhook/set",
                    json={
                        "url": webhook_url,
                        "webhook_by_events": False,
                        "webhook_base64": False,
                        "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE"]
                    },
                    headers={
                        "Content-Type": "application/json",
                        "token": instance_token,
                    }
                )
                print(f"✅ Webhook set response: {r.status_code} {r.text[:200]}")
                return r.json() if r.content else {"status": r.status_code}
        except Exception as e:
            print(f"⚠️ set_webhook error: {e}")
            return {"error": str(e)}

    # ── STATUS DA INSTÂNCIA ─────────────────────────────────────────────────
    async def get_instance_status(self, instance: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{settings.UAZAP_BASE_URL}/instance/connectionState/{instance}",
                    headers={"token": settings.UAZAP_API_KEY}
                )
                return r.json()
        except Exception as e:
            return {"error": str(e)}

    # ── QR CODE ─────────────────────────────────────────────────────────────
    async def get_qrcode(self, instance: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{settings.UAZAP_BASE_URL}/instance/connect/{instance}",
                    headers={"token": settings.UAZAP_API_KEY}
                )
                return r.json()
        except Exception as e:
            return {"error": str(e)}

    # ── STATUS DA INSTÂNCIA ─────────────────────────────────────────────────
    async def get_instance_status(self, instance: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{settings.UAZAP_BASE_URL}/instance/connectionState/{instance}",
                    headers={"token": settings.UAZAP_API_KEY}
                )
                return r.json()
        except Exception as e:
            return {"error": str(e)}

    # ── QR CODE ─────────────────────────────────────────────────────────────
    async def get_qrcode(self, instance: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{settings.UAZAP_BASE_URL}/instance/connect/{instance}",
                    headers={"token": settings.UAZAP_API_KEY}
                )
                return r.json()
        except Exception as e:
            return {"error": str(e)}


whatsapp_client = WhatsAppService()


async def process_incoming_webhook(payload: dict, workspace_id: str):
    """
    Processa webhook recebido do UazAP v2.
    Estrutura: { EventType, message: {content, chatid, fromMe}, chat: {phone} }
    """
    try:
        from app.services.message_service import handle_incoming_message

        # ── UazAP v2 format ──────────────────────────────────────────────
        event_type = payload.get("EventType", "") or payload.get("event", "")
        msg        = payload.get("message", {})
        chat       = payload.get("chat", {})

        # Ignorar eventos que não são mensagens
        if event_type not in ("messages", "message", "messages.upsert", ""):
            skip = {"connection", "qrcode", "presence", "ack", "call", "group"}
            if any(s in event_type.lower() for s in skip):
                print(f"⏭️ Ignorando evento {event_type!r}")
                return

        # Ignorar mensagens enviadas pelo bot
        from_me = msg.get("fromMe", False) or msg.get("from_me", False)
        if from_me:
            print(f"⏭️ Ignorando fromMe")
            return

        # Extrair telefone — UazAP v2 usa chatid ou chat.phone
        chat_id = msg.get("chatid", "") or chat.get("wa_chatid", "")
        phone = chat_id.replace("@s.whatsapp.net", "").replace("@c.us", "").replace("@g.us", "")
        if not phone:
            # fallback: chat.phone
            phone = chat.get("phone", "").replace("+", "").replace(" ", "").replace("-", "")
        if not phone:
            print(f"⚠️ Sem telefone no payload")
            return

        # Ignorar grupos
        if "@g.us" in chat_id or chat.get("wa_isGroup", False):
            print(f"⏭️ Ignorando grupo {chat_id}")
            return

        # Extrair conteúdo — UazAP v2 usa message.content diretamente
        content      = msg.get("content", "") or msg.get("body", "") or msg.get("text", "")
        message_type = "text"
        media_data   = None
        media_mime   = None

        msg_type = msg.get("type", "") or msg.get("messageType", "") or msg.get("wa_lastMessageType", "")
        msg_type_lower = msg_type.lower()

        if "audio" in msg_type_lower:
            message_type = "audio"
        elif "image" in msg_type_lower:
            message_type = "image"
        elif "video" in msg_type_lower:
            message_type = "video"
        elif "document" in msg_type_lower or "pdf" in msg_type_lower:
            message_type = "document"
        elif "button" in msg_type_lower or "list" in msg_type_lower:
            message_type = "button_reply"
            content = content or msg.get("buttonOrListid", "")

        print(f"✅ Mensagem extraída: phone={phone} type={message_type} content={content!r}")

        if not content and message_type == "text":
            return  # mensagem vazia

        # Delegar ao message_service
        await handle_incoming_message(
            workspace_id = workspace_id,
            phone        = phone,
            content      = content,
            message_type = message_type,
            media_data   = media_data,
            media_mime   = media_mime,
            raw_payload  = payload,
        )

    except Exception as e:
        import logging
        logging.error(f"process_incoming_webhook error: {e}")