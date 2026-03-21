"""
app/api/v1/media.py - Upload e gerenciamento de arquivos de mídia
"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse
from typing import Optional
import aiofiles
import uuid
from pathlib import Path

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

    supabase = get_supabase()
    result = supabase.table("media_files").insert({
        "workspace_id": workspace_id,
        "file_name": display_name or file.filename,
        "file_size": len(content),
        "mime_type": mime,
        "storage_path": str(storage_path),
        "public_url": public_url,
    }).execute()

    return result.data[0] if result.data else {
        "file_name": display_name or file.filename,
        "public_url": public_url,
    }


@router.get("/serve/{workspace_id}/{category}/{filename}")
async def serve_file(workspace_id: str, category: str, filename: str):
    for base in [
        UPLOAD_PATH / workspace_id / category / filename,
        Path("uploads") / workspace_id / category / filename,
        Path("E:/nutty-saas/uploads") / workspace_id / category / filename,
    ]:
        if base.exists():
            return FileResponse(str(base))
    raise HTTPException(status_code=404, detail="Arquivo não encontrado")


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
        p = Path(rec.data[0]["storage_path"])
        if p.exists():
            p.unlink()
    supabase.table("media_files").delete().eq("id", media_id).eq(
        "workspace_id", workspace_id).execute()
    return {"status": "deleted"}
