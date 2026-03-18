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
    Processa webhook recebido do UazAP.
    Extrai a mensagem, salva na conversa e aciona a IA se necessário.
    """
    import logging
    import json
    logger = logging.getLogger(__name__)

    try:
        from app.services.message_service import handle_incoming_message

        # Log do payload completo para debug
        logger.info(f"📨 Webhook recebido workspace={workspace_id} payload={json.dumps(payload)[:500]}")

        data    = payload.get("data", {})
        key     = data.get("key", {})
        msg     = data.get("message", {})
        event   = payload.get("event", "")

        logger.info(f"📨 event={event!r} fromMe={key.get('fromMe')} remoteJid={key.get('remoteJid')} msg_keys={list(msg.keys())}")

        # Só processa mensagens recebidas (não enviadas pelo bot)
        if key.get("fromMe", False):
            logger.info("⏭️ Ignorando mensagem própria")
            return

        # Se o evento for de status/conexão, ignora
        skip_events = {"connection.update", "qrcode.updated", "presence.update",
                       "message_ack", "call", "group_update"}
        if event in skip_events:
            logger.info(f"⏭️ Ignorando evento {event}")
            return

        # Extrair telefone do remetente
        remote_jid = key.get("remoteJid", "")
        phone = remote_jid.replace("@s.whatsapp.net", "").replace("@c.us", "")
        if not phone:
            return

        # Extrair conteúdo da mensagem
        content      = ""
        message_type = "text"
        media_data   = None
        media_mime   = None

        if msg.get("conversation"):
            content = msg["conversation"]
        elif msg.get("extendedTextMessage"):
            content = msg["extendedTextMessage"].get("text", "")
        elif msg.get("imageMessage"):
            content      = msg["imageMessage"].get("caption", "")
            message_type = "image"
        elif msg.get("audioMessage"):
            message_type = "audio"
        elif msg.get("documentMessage"):
            content      = msg["documentMessage"].get("fileName", "")
            message_type = "document"
        elif msg.get("videoMessage"):
            content      = msg["videoMessage"].get("caption", "")
            message_type = "video"
        elif msg.get("buttonsResponseMessage"):
            content      = msg["buttonsResponseMessage"].get("selectedDisplayText", "")
            message_type = "button_reply"
        elif msg.get("listResponseMessage"):
            content      = msg["listResponseMessage"].get("title", "")
            message_type = "list_reply"

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
