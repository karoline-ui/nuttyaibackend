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
        print(f"📤 send_text: phone={phone} workspace={workspace_id} msg={message[:80]!r}")
        result = await self._post("/send/text", {
            "number": phone,
            "text": message,
            "delay": 1000,
        }, workspace_id=workspace_id)
        print(f"📤 send_text result: {result}")
        return result

    # ── IMAGEM ──────────────────────────────────────────────────────────────
    async def send_image(self, phone: str, url: str, caption: str, workspace_id: str) -> dict:
        return await self._post("/send/media", {
            "number": phone,
            "type": "image",
            "file": url,
            "text": caption,
            "delay": 1000,
        }, workspace_id=workspace_id)

    # ── ÁUDIO ───────────────────────────────────────────────────────────────
    async def send_audio(self, phone: str, url: str, workspace_id: str) -> dict:
        return await self._post("/send/media", {
            "number": phone,
            "type": "ptt",
            "file": url,
            "delay": 1000,
        }, workspace_id=workspace_id)

    # ── DOCUMENTO ───────────────────────────────────────────────────────────
    async def send_document(self, phone: str, url: str, filename: str, workspace_id: str) -> dict:
        return await self._post("/send/media", {
            "number": phone,
            "type": "document",
            "file": url,
            "docName": filename,
            "text": filename,
            "delay": 1000,
        }, workspace_id=workspace_id)

    # ── BOTÕES RÁPIDOS (até 3) ───────────────────────────────────────────────
    async def send_buttons(self, phone: str, message: str, buttons: list, workspace_id: str) -> dict:
        """
        Envia mensagem com botões interativos (reply buttons).
        Payload UazAP v2 / Evolution API padrão.
        """
        return await self._post("/send/menu", {
            "number": phone,
            "type": "button",
            "text": message,
            "choices": [f"{btn}|btn_{i}" for i, btn in enumerate(buttons[:3])],
            "delay": 1000,
        }, workspace_id=workspace_id)

    # ── LISTA INTERATIVA ────────────────────────────────────────────────────
    async def send_list(self, phone: str, message: str, title: str, items: list, workspace_id: str) -> dict:
        """
        Envia lista interativa nativa do WhatsApp.
        Agrupa tudo numa seção única.
        """
        choices = [f"[{title}]"] + [f"{item}|row_{i}" for i, item in enumerate(items[:10])]
        return await self._post("/send/menu", {
            "number": phone,
            "type": "list",
            "text": message,
            "choices": choices,
            "listButton": "Ver opções",
            "delay": 1000,
        }, workspace_id=workspace_id)

    # ── LOCALIZAÇÃO ─────────────────────────────────────────────────────────
    async def send_location(self, phone: str, lat: float, lng: float, name: str, address: str, workspace_id: str) -> dict:
        return await self._post("/send/location", {
            "number": phone,
            "lat": lat,
            "lng": lng,
            "name": name,
            "address": address,
            "delay": 1000,
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
        """POST /webhook — modo simples, cria ou atualiza webhook único da instância"""
        try:
            conn = await self._get_connection(workspace_id)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{conn['url']}/webhook",
                    json={
                        "url": webhook_url,
                        "events": ["messages"],
                        "excludeMessages": ["wasSentByApi"],
                    },
                    headers={
                        "Content-Type": "application/json",
                        "token": conn["api_key"],
                    }
                )
                print(f"✅ Webhook configurado: {r.status_code} {r.text[:200]}")
                return r.json() if r.content else {"status": r.status_code}
        except Exception as e:
            print(f"⚠️ set_webhook error: {e}")
            return {"error": str(e)}

    # ── STATUS DA INSTÂNCIA ─────────────────────────────────────────────────
    async def get_status(self, workspace_id: str) -> dict:
        """GET /instance/status — retorna status da conexão"""
        try:
            conn = await self._get_connection(workspace_id)
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{conn['url']}/instance/status",
                    headers={"token": conn["api_key"]}
                )
                data = r.json()
                return {"connected": data.get("status") == "connected", "state": data.get("status"), **data}
        except Exception as e:
            return {"error": str(e), "connected": False}

    # ── QR CODE / CONNECT ────────────────────────────────────────────────────
    async def get_qrcode(self, workspace_id: str) -> dict:
        """POST /instance/connect — gera QR code para conexão"""
        try:
            conn = await self._get_connection(workspace_id)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(
                    f"{conn['url']}/instance/connect",
                    json={},
                    headers={"token": conn["api_key"], "Content-Type": "application/json"}
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
        raw_content  = msg.get("content", "") or msg.get("body", "") or msg.get("text", "")
        message_type = "text"
        media_data   = None
        media_mime   = None

        # Se content é dict E tem URL/mediaKey, é mídia real
        # Se não tiver, pode ser dado de contato/perfil — trata como texto
        if isinstance(raw_content, dict) and (
            raw_content.get("URL") or raw_content.get("url") or 
            raw_content.get("mediaKey") or raw_content.get("directPath")
        ):
            mime = raw_content.get("mimetype", "")
            wa_type = chat.get("wa_lastMessageType", "") or msg.get("type", "") or ""
            wa_type_lower = wa_type.lower()
            if "audio" in mime or "ogg" in mime or "opus" in mime or "ptt" in wa_type_lower or "audio" in wa_type_lower:
                message_type = "audio"
            elif "video" in mime or "mp4" in mime or "video" in wa_type_lower:
                message_type = "video"
            elif "pdf" in mime or "document" in wa_type_lower:
                message_type = "document"
            else:
                message_type = "image"
            caption = raw_content.get("caption", "")
            # Transcreve mídia aqui — chega como texto para o flow
            try:
                from app.services.whatsapp_media import media_handler as _mh
                transcribed = await _mh.process_media(message_type, raw_content, caption)
                content = transcribed
                print(f"✅ Mídia transcrita: {content[:100]!r}")
            except Exception as me:
                print(f"⚠️ Transcrição error: {me}")
                content = caption or f"[{message_type}]"
            raw_media_dict_pre = raw_content
        else:
            msg_type = msg.get("type", "") or msg.get("messageType", "") or chat.get("wa_lastMessageType", "")
            msg_type_lower = msg_type.lower()
            if "audio" in msg_type_lower or "ptt" in msg_type_lower:
                message_type = "audio"
            elif "image" in msg_type_lower or "sticker" in msg_type_lower:
                message_type = "image"
            elif "video" in msg_type_lower:
                message_type = "video"
            elif "document" in msg_type_lower or "pdf" in msg_type_lower:
                message_type = "document"
            elif "button" in msg_type_lower or "list" in msg_type_lower:
                message_type = "button_reply"
            content = str(raw_content) if raw_content else ""
            raw_media_dict_pre = None

        print(f"🔍 message_type={message_type} is_media={raw_media_dict_pre is not None}")

        if message_type == "button_reply":
            content = content or msg.get("buttonOrListid", "")

        # raw_media_dict já foi preservado antes
        raw_media_dict = raw_media_dict_pre
        content_str = content or ""

        print(f"✅ Mensagem extraída: phone={phone} type={message_type} content={content_str[:80]!r}")

        if not content_str and message_type == "text":
            return  # mensagem vazia

        # Delegar ao message_service
        await handle_incoming_message(
            workspace_id   = workspace_id,
            phone          = phone,
            content        = content_str,
            message_type   = message_type,
            media_data     = media_data,
            media_mime     = media_mime,
            raw_payload    = payload,
            raw_media_dict = raw_media_dict,
            contact_name   = chat.get("wa_name") or chat.get("wa_contactName") or "",
        )

    except Exception as e:
        import logging
        logging.error(f"process_incoming_webhook error: {e}")
