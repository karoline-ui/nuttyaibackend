"""
Nutty.AI v6.1 — Media Handler
Mídia WhatsApp é criptografada E2E. Processo:
1. Baixa arquivo criptografado da URL (mmg.whatsapp.net)
2. Descriptografa com mediaKey usando HKDF + AES-256-CBC
3. Envia bytes limpos para Gemini (visão/áudio) ou PyMuPDF (PDF)

v6.1: Suporte Gemini API (era só OpenRouter). Usa Gemini se GEMINI_API_KEY
disponível, senão fallback OpenRouter.
"""
import base64
import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from typing import Optional, Tuple

from app.core.config import settings

# Provider detection
GEMINI_API_KEY = getattr(settings, "GEMINI_API_KEY", "") or ""
GEMINI_MODEL = getattr(settings, "GEMINI_MODEL", "") or "gemini-2.5-flash"
OPENROUTER_API_KEY = ""
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
VISION_MODEL = ""

USE_GEMINI = bool(GEMINI_API_KEY)

# WhatsApp media HKDF info strings
MEDIA_HKDF_INFO = {
    "image": b"WhatsApp Image Keys",
    "sticker": b"WhatsApp Image Keys",
    "ptt": b"WhatsApp Audio Keys",
    "audio": b"WhatsApp Audio Keys",
    "video": b"WhatsApp Video Keys",
    "document": b"WhatsApp Document Keys",
}


def _decrypt_whatsapp_media(encrypted_data: bytes, media_key_b64: str, media_type: str) -> bytes:
    """Descriptografa mídia WhatsApp E2E."""
    media_key = base64.b64decode(media_key_b64)
    info = MEDIA_HKDF_INFO.get(media_type, b"WhatsApp Image Keys")

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=112,
        salt=None,
        info=info,
        backend=default_backend(),
    )
    expanded = hkdf.derive(media_key)

    iv = expanded[:16]
    cipher_key = expanded[16:48]

    file_data = encrypted_data[:-10]

    cipher = Cipher(algorithms.AES(cipher_key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(file_data) + decryptor.finalize()

    if decrypted:
        pad_len = decrypted[-1]
        if 0 < pad_len <= 16 and all(b == pad_len for b in decrypted[-pad_len:]):
            decrypted = decrypted[:-pad_len]

    return decrypted


class MediaHandler:
    def __init__(self):
        self.use_gemini = USE_GEMINI
        self.gemini_key = GEMINI_API_KEY
        self.gemini_model = GEMINI_MODEL
        self.openrouter_key = OPENROUTER_API_KEY
        print(f"[Media] Provider: {'GEMINI' if self.use_gemini else 'OPENROUTER'}")

    async def download_encrypted(self, url: str) -> Optional[bytes]:
        """Baixa arquivo criptografado do WhatsApp."""
        if not url:
            return None
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    print(f"[Media] Downloaded: {len(resp.content)} bytes")
                    return resp.content
                print(f"[Media] Download failed: {resp.status_code}")
                return None
        except Exception as e:
            print(f"[Media] Download error: {e}")
            return None

    async def decrypt_media(self, content_dict: dict, media_type: str) -> Tuple[Optional[bytes], str]:
        """Baixa e descriptografa mídia WhatsApp."""
        url = content_dict.get("URL") or content_dict.get("url", "")
        media_key = content_dict.get("mediaKey") or content_dict.get("MediaKey", "")
        mimetype = content_dict.get("mimetype") or content_dict.get("Mimetype", "")

        if not url or not media_key:
            print(f"[Media] Missing URL or mediaKey")
            return None, ""

        encrypted = await self.download_encrypted(url)
        if not encrypted:
            return None, ""

        try:
            decrypted = _decrypt_whatsapp_media(encrypted, media_key, media_type)
            print(f"[Media] Decrypted: {len(decrypted)} bytes, mime={mimetype}")
            return decrypted, mimetype or "application/octet-stream"
        except Exception as e:
            print(f"[Media] Decrypt error: {e}")
            import traceback; traceback.print_exc()
            return None, ""

    # ============================================================
    # GEMINI API calls
    # ============================================================

    async def _gemini_vision(self, image_bytes: bytes, mimetype: str, prompt: str) -> str:
        """Envia imagem para Gemini API."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        if "png" in mimetype:
            mime = "image/png"
        elif "webp" in mimetype:
            mime = "image/webp"
        else:
            mime = "image/jpeg"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_key}"

        payload = {
            "contents": [{
                "parts": [
                    {"inlineData": {"mimeType": mime, "data": b64}},
                    {"text": prompt},
                ]
            }],
            "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.2},
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                return parts[0].get("text", "") if parts else ""
            print(f"[Media] Gemini vision error {resp.status_code}: {resp.text[:200]}")
            return ""

    async def _gemini_audio(self, audio_bytes: bytes, mimetype: str, prompt: str) -> str:
        """Envia áudio para Gemini API."""
        b64 = base64.b64encode(audio_bytes).decode("utf-8")

        # Gemini aceita vários mimetypes de áudio
        if "ogg" in mimetype or "opus" in mimetype:
            mime = "audio/ogg"
        elif "mp4" in mimetype or "m4a" in mimetype:
            mime = "audio/mp4"
        elif "mpeg" in mimetype or "mp3" in mimetype:
            mime = "audio/mpeg"
        elif "wav" in mimetype:
            mime = "audio/wav"
        else:
            mime = "audio/ogg"

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_key}"

        payload = {
            "contents": [{
                "parts": [
                    {"inlineData": {"mimeType": mime, "data": b64}},
                    {"text": prompt},
                ]
            }],
            "generationConfig": {"maxOutputTokens": 1000, "temperature": 0.1},
        }

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                return parts[0].get("text", "") if parts else ""
            print(f"[Media] Gemini audio error {resp.status_code}: {resp.text[:200]}")
            return ""

    # ============================================================
    # OPENROUTER API calls (fallback)
    # ============================================================

    async def _openrouter_vision(self, image_bytes: bytes, mimetype: str, prompt: str) -> str:
        """Envia imagem para OpenRouter."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        if "png" in mimetype:
            mime = "image/png"
        elif "webp" in mimetype:
            mime = "image/webp"
        else:
            mime = "image/jpeg"

        messages = [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}]

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(OPENROUTER_URL, json={
                "model": VISION_MODEL, "messages": messages,
                "max_tokens": 1000, "temperature": 0.2,
            }, headers={
                "Authorization": f"Bearer {self.openrouter_key}",
                "Content-Type": "application/json",
            })
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
            print(f"[Media] OpenRouter vision error {resp.status_code}: {resp.text[:200]}")
            return ""

    async def _openrouter_audio(self, audio_bytes: bytes, mimetype: str, prompt: str) -> str:
        """Envia áudio para OpenRouter."""
        b64 = base64.b64encode(audio_bytes).decode("utf-8")
        if "ogg" in mimetype or "opus" in mimetype:
            fmt = "ogg"
        elif "mp4" in mimetype or "m4a" in mimetype:
            fmt = "mp4"
        else:
            fmt = "ogg"

        messages = [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": b64, "format": fmt}},
            {"type": "text", "text": prompt},
        ]}]

        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(OPENROUTER_URL, json={
                "model": VISION_MODEL, "messages": messages,
                "max_tokens": 1000, "temperature": 0.1,
            }, headers={
                "Authorization": f"Bearer {self.openrouter_key}",
                "Content-Type": "application/json",
            })
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"].strip()
                return text if text else ""
            print(f"[Media] OpenRouter audio error {resp.status_code}: {resp.text[:200]}")
            return ""

    # ============================================================
    # Métodos públicos
    # ============================================================

    async def describe_image(self, image_bytes: bytes, mimetype: str) -> str:
        """Descreve imagem usando Gemini ou OpenRouter."""
        prompt = (
            "Descreva esta imagem de forma objetiva e concisa em português brasileiro. "
            "Se houver texto na imagem, transcreva-o completamente. "
            "Se for um documento, exame, receita ou pedido médico/veterinário, "
            "extraia TODAS as informações: nome do paciente, espécie, raça, idade, "
            "exames solicitados, posições, observações, nome do médico. "
            "Responda apenas com a descrição/transcrição."
        )
        try:
            if self.use_gemini:
                result = await self._gemini_vision(image_bytes, mimetype, prompt)
            else:
                result = await self._openrouter_vision(image_bytes, mimetype, prompt)
            return result or "[Imagem recebida - não foi possível analisar]"
        except Exception as e:
            print(f"[Media] describe_image error: {e}")
            return "[Imagem recebida - erro ao processar]"

    async def transcribe_audio(self, audio_bytes: bytes, mimetype: str) -> str:
        """Transcreve áudio usando Gemini ou OpenRouter."""
        prompt = "Transcreva este áudio em português brasileiro. Retorne APENAS a transcrição, sem explicações."
        try:
            if self.use_gemini:
                result = await self._gemini_audio(audio_bytes, mimetype, prompt)
            else:
                result = await self._openrouter_audio(audio_bytes, mimetype, prompt)
            return result or "[áudio inaudível]"
        except Exception as e:
            print(f"[Media] transcribe error: {e}")
            return "[Áudio - erro ao processar]"

    async def extract_pdf_text(self, pdf_bytes: bytes) -> str:
        """Extrai texto de PDF com PyMuPDF."""
        try:
            import fitz
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                text = "\n".join([page.get_text() for page in doc]).strip()
            return text[:3000] if text else "[PDF sem texto extraível]"
        except ImportError:
            return "[PDF - PyMuPDF não instalado]"
        except Exception as e:
            print(f"[Media] PDF error: {e}")
            return "[PDF - erro ao extrair]"

    async def process_media(
        self, media_type: str, content_dict: dict, caption: str = ""
    ) -> str:
        """Método principal: baixa, descriptografa e processa mídia."""
        if not content_dict or not (content_dict.get("URL") or content_dict.get("url")):
            return caption or f"[Cliente enviou {media_type} mas sem dados]"

        decrypted, mimetype = await self.decrypt_media(content_dict, media_type)
        if not decrypted:
            return caption or f"[Cliente enviou {media_type} - falha no download/descriptografia]"

        try:
            if media_type in ("image", "sticker"):
                desc = await self.describe_image(decrypted, mimetype)
                prefix = f"{caption}\n\n" if caption else ""
                return f"{prefix}[DESCRIÇÃO DA IMAGEM]: {desc}"

            elif media_type in ("ptt", "audio"):
                trans = await self.transcribe_audio(decrypted, mimetype)
                return f"[TRANSCRIÇÃO DO ÁUDIO]: {trans}"

            elif media_type in ("document", "file"):
                if "pdf" in mimetype.lower():
                    pdf = await self.extract_pdf_text(decrypted)
                    return f"[CONTEÚDO DO PDF]: {pdf}"
                return caption or f"[Documento ({mimetype}) recebido]"

            elif media_type == "video":
                return caption or "[Cliente enviou um vídeo]"

            return caption or f"[Mídia '{media_type}' recebida]"

        except Exception as e:
            print(f"[Media] process error ({media_type}): {e}")
            return caption or f"[Erro ao processar {media_type}]"


media_handler = MediaHandler()