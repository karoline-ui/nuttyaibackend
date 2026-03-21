"""
app/api/v1/media.py - Upload e gerenciamento de arquivos de mídia
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse
from typing import Optional
import aiofiles
import os
import uuid
from pathlib import Path
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google")
import google.generativeai as genai
import base64

from app.core.config import settings
from app.core.database import get_supabase

router = APIRouter()

UPLOAD_PATH = Path(settings.UPLOAD_DIR)
UPLOAD_PATH.mkdir(parents=True, exist_ok=True)

ALLOWED_TYPES = [
    "image/jpeg","image/png","image/webp","image/gif",
    "audio/ogg","audio/mp4","audio/mpeg","audio/wav","audio/webm",
    "video/mp4","video/webm",
    "application/pdf",
]

def get_category(mime: str) -> str:
    if mime.startswith("image/"): return "images"
    if mime.startswith("audio/"): return "audio"
    if mime.startswith("video/"): return "video"
    if mime == "application/pdf": return "documents"
    return "others"


async def process_with_gemini(content: bytes, mime: str, category: str) -> dict:
    """Processa arquivo com Gemini usando a API key do .env"""
    result = {"transcription": None, "description": None}
    
    try:
        api_key = settings.GEMINI_API_KEY
        if not api_key or api_key.startswith("AIzaSy") is False:
            return {"transcription": "API Key Gemini não configurada", "description": None}
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(settings.GEMINI_MODEL or "gemini-2.5-flash-preview-04-17")
        
        if category == "images":
            response = model.generate_content([
                "Descreva detalhadamente esta imagem em português. Seja preciso e útil.",
                {"mime_type": mime, "data": base64.b64encode(content).decode()}
            ])
            result["description"] = response.text
            
        elif category in ["audio", "video"]:
            response = model.generate_content([
                "Transcreva o conteúdo deste áudio/vídeo em português. Seja preciso.",
                {"mime_type": mime, "data": base64.b64encode(content).decode()}
            ])
            result["transcription"] = response.text
            
        elif category == "documents":
            try:
                import fitz
                import io
                doc = fitz.open(stream=content, filetype="pdf")
                text = ""
                for page in doc:
                    text += page.get_text()
                doc.close()
                result["transcription"] = text[:5000]
            except Exception as e:
                result["transcription"] = f"Erro ao extrair PDF: {str(e)}"
                
    except Exception as e:
        result["transcription"] = f"Não foi possível processar: {str(e)}"
    
    return result


@router.post("/upload")
async def upload_media(
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
    auto_process: bool = Form(False),
):
    mime = file.content_type or "application/octet-stream"
    
    # Aceitar mais tipos
    if mime not in ALLOWED_TYPES and not mime.startswith(("image/","audio/","video/")):
        raise HTTPException(status_code=400, detail=f"Tipo não suportado: {mime}")
    
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=413, detail=f"Arquivo muito grande: {size_mb:.1f}MB")
    
    category = get_category(mime)
    file_ext = Path(file.filename or "file").suffix or ".bin"
    unique_name = f"{uuid.uuid4()}{file_ext}"
    storage_path = UPLOAD_PATH / workspace_id / category / unique_name
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    
    async with aiofiles.open(storage_path, "wb") as f:
        await f.write(content)
    
    public_url = f"/api/v1/media/serve/{workspace_id}/{category}/{unique_name}"
    
    # Processar com IA
    ai_result = {"transcription": None, "description": None}
    if auto_process:
        ai_result = await process_with_gemini(content, mime, category)
    
    supabase = get_supabase()
    result = supabase.table("media_files").insert({
        "workspace_id": workspace_id,
        "file_name": file.filename,
        "file_size": len(content),
        "mime_type": mime,
        "storage_path": str(storage_path),
        "public_url": public_url,
        "transcription": ai_result.get("transcription"),
        "description": ai_result.get("description"),
    }).execute()
    
    return result.data[0] if result.data else {
        "file_name": file.filename, "public_url": public_url, **ai_result
    }


@router.get("/serve/{workspace_id}/{category}/{filename}")
async def serve_file(workspace_id: str, category: str, filename: str):
    """Serve arquivo local — tenta múltiplos paths"""
    # Tentar path direto
    paths_to_try = [
        UPLOAD_PATH / workspace_id / category / filename,
        Path(settings.UPLOAD_DIR) / workspace_id / category / filename,
        Path("uploads") / workspace_id / category / filename,
        Path("E:/nutty-saas/uploads") / workspace_id / category / filename,
    ]
    
    for file_path in paths_to_try:
        if file_path.exists():
            return FileResponse(str(file_path))
    
    # Tentar buscar no banco pelo public_url
    supabase = get_supabase()
    expected_url = f"/api/v1/media/serve/{workspace_id}/{category}/{filename}"
    db_file = supabase.table("media_files").select("storage_path").eq(
        "public_url", expected_url
    ).single().execute()
    
    if db_file.data:
        storage_path = Path(db_file.data["storage_path"])
        if storage_path.exists():
            return FileResponse(str(storage_path))
    
    raise HTTPException(status_code=404, detail=f"Arquivo não encontrado: {filename}")


@router.get("")
async def list_media(workspace_id: str, mime_category: Optional[str] = None, limit: int = 50):
    supabase = get_supabase()
    q = supabase.table("media_files").select("*").eq("workspace_id", workspace_id)
    if mime_category == "images":    q = q.like("mime_type", "image/%")
    elif mime_category == "audio":   q = q.like("mime_type", "audio/%")
    elif mime_category == "video":   q = q.like("mime_type", "video/%")
    elif mime_category == "documents": q = q.eq("mime_type", "application/pdf")
    return (q.order("created_at", desc=True).limit(limit).execute()).data or []


@router.delete("/{media_id}")
async def delete_media(media_id: str, workspace_id: str):
    supabase = get_supabase()
    file = supabase.table("media_files").select("storage_path").eq(
        "id", media_id).eq("workspace_id", workspace_id).single().execute()
    if file.data:
        try: os.remove(file.data["storage_path"])
        except: pass
    supabase.table("media_files").delete().eq("id", media_id).execute()
    return {"status": "deleted"}


@router.post("/{media_id}/add-to-knowledge")
async def add_to_knowledge(media_id: str, workspace_id: str, title: str, tags: Optional[str] = None):
    supabase = get_supabase()
    media = supabase.table("media_files").select("*").eq(
        "id", media_id).eq("workspace_id", workspace_id).single().execute()
    if not media.data:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    content = media.data.get("transcription") or media.data.get("description") or ""
    if not content:
        raise HTTPException(status_code=400, detail="Arquivo sem conteúdo processado")
    result = supabase.table("knowledge_base").insert({
        "workspace_id": workspace_id, "title": title, "content": content,
        "media_file_id": media_id,
        "tags": [t.strip() for t in tags.split(",")] if tags else [],
    }).execute()
    return result.data[0] if result.data else {}
