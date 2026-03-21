"""
app/api/v1/media.py - Upload e gerenciamento de arquivos de mídia via Supabase Storage
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from typing import Optional
import uuid
from pathlib import Path

from app.core.database import get_supabase

router = APIRouter()

ALLOWED_TYPES = [
    "image/jpeg","image/png","image/webp","image/gif",
    "audio/ogg","audio/mp4","audio/mpeg","audio/wav","audio/webm",
    "video/mp4","video/webm",
    "application/pdf",
]

MAX_SIZE_MB = 50

def get_category(mime: str) -> str:
    if mime.startswith("image/"): return "images"
    if mime.startswith("audio/"): return "audio"
    if mime.startswith("video/"): return "video"
    if mime == "application/pdf": return "documents"
    return "others"


@router.post("/upload")
async def upload_media(
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
    display_name: str = Form(""),
):
    mime = file.content_type or "application/octet-stream"
    if mime not in ALLOWED_TYPES and not mime.startswith(("image/","audio/","video/")):
        raise HTTPException(status_code=400, detail=f"Tipo não suportado: {mime}")

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_SIZE_MB:
        raise HTTPException(status_code=413, detail=f"Arquivo muito grande: {size_mb:.1f}MB")

    category = get_category(mime)
    file_ext = Path(file.filename or "file").suffix or ".bin"
    unique_name = f"{uuid.uuid4()}{file_ext}"
    storage_path = f"{workspace_id}/{category}/{unique_name}"

    supabase = get_supabase()

    # Upload para Supabase Storage
    try:
        res = supabase.storage.from_("media").upload(
            path=storage_path,
            file=content,
            file_options={"content-type": mime, "upsert": "true"},
        )
        print(f"[Media] upload res: {res}")
        if hasattr(res, 'error') and res.error:
            raise Exception(str(res.error))
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Erro no upload: {str(e)}")

    # URL pública do Supabase Storage
    public_url = supabase.storage.from_("media").get_public_url(storage_path)

    # Salva registro no banco
    result = supabase.table("media_files").insert({
        "workspace_id": workspace_id,
        "file_name": display_name or file.filename,
        "file_size": len(content),
        "mime_type": mime,
        "storage_path": storage_path,
        "public_url": public_url,
    }).execute()

    return result.data[0] if result.data else {
        "file_name": display_name or file.filename,
        "public_url": public_url,
    }


@router.get("")
async def list_media(workspace_id: str, mime_category: Optional[str] = None, limit: int = 50):
    supabase = get_supabase()
    q = supabase.table("media_files").select("*").eq("workspace_id", workspace_id)
    if mime_category:
        q = q.ilike("mime_type", f"{mime_category}/%")
    result = q.order("created_at", desc=True).limit(limit).execute()
    return result.data or []


@router.delete("/{media_id}")
async def delete_media(media_id: str, workspace_id: str):
    supabase = get_supabase()
    rec = supabase.table("media_files").select("storage_path").eq(
        "id", media_id).eq("workspace_id", workspace_id).limit(1).execute()
    if rec.data:
        try:
            supabase.storage.from_("media").remove([rec.data[0]["storage_path"]])
        except Exception:
            pass
    supabase.table("media_files").delete().eq("id", media_id).eq(
        "workspace_id", workspace_id).execute()
    return {"status": "deleted"}