"""
app/api/v1/contacts.py
"""
from fastapi import APIRouter, HTTPException
from app.core.database import get_supabase
router = APIRouter()

@router.get("")
async def list_contacts(workspace_id: str, search: str = "", limit: int = 100, offset: int = 0):
    supabase = get_supabase()
    q = supabase.table("contacts").select("*").eq("workspace_id", workspace_id)
    if search:
        q = q.or_(f"name.ilike.%{search}%,phone.ilike.%{search}%")
    result = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return result.data

@router.post("")
async def create_contact(workspace_id: str, body: dict):
    supabase = get_supabase()
    result = supabase.table("contacts").insert({"workspace_id": workspace_id, **body}).execute()
    return result.data[0] if result.data else {}

@router.patch("/{contact_id}")
async def update_contact(contact_id: str, workspace_id: str, body: dict):
    supabase = get_supabase()
    result = supabase.table("contacts").update(body).eq("id", contact_id).eq("workspace_id", workspace_id).execute()
    return result.data[0] if result.data else {}

@router.delete("/{contact_id}")
async def delete_contact(contact_id: str, workspace_id: str):
    supabase = get_supabase()
    supabase.table("contacts").delete().eq("id", contact_id).eq("workspace_id", workspace_id).execute()
    return {"status": "deleted"}


# ── TAGS ────────────────────────────────────────────────────────────────────

@router.get("/tags/all")
async def list_all_tags(workspace_id: str):
    """Lista todas as tags únicas usadas nos contatos do workspace"""
    supabase = get_supabase()
    result = supabase.table("contacts").select("tags").eq("workspace_id", workspace_id).execute()
    all_tags: dict = {}
    for row in (result.data or []):
        for tag in (row.get("tags") or []):
            all_tags[tag] = all_tags.get(tag, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(all_tags.items())]


@router.post("/tags/add")
async def add_tag_to_contacts(workspace_id: str, body: dict):
    """Adiciona tag a múltiplos contatos de uma vez"""
    supabase = get_supabase()
    tag = body.get("tag", "").strip().lower()
    contact_ids = body.get("contact_ids", [])
    if not tag:
        return {"error": "tag required"}
    updated = 0
    for cid in contact_ids:
        row = supabase.table("contacts").select("tags").eq("id", cid).single().execute()
        current = row.data.get("tags") or [] if row.data else []
        if tag not in current:
            supabase.table("contacts").update({"tags": current + [tag]}).eq("id", cid).execute()
            updated += 1
    return {"updated": updated}


@router.post("/tags/remove")
async def remove_tag_from_contacts(workspace_id: str, body: dict):
    """Remove tag de múltiplos contatos"""
    supabase = get_supabase()
    tag = body.get("tag", "").strip().lower()
    contact_ids = body.get("contact_ids", [])
    updated = 0
    for cid in contact_ids:
        row = supabase.table("contacts").select("tags").eq("id", cid).single().execute()
        current = row.data.get("tags") or [] if row.data else []
        if tag in current:
            supabase.table("contacts").update({"tags": [t for t in current if t != tag]}).eq("id", cid).execute()
            updated += 1
    return {"updated": updated}


@router.patch("/{contact_id}/tags")
async def set_contact_tags(contact_id: str, workspace_id: str, body: dict):
    """Define exatamente as tags de um contato"""
    supabase = get_supabase()
    tags = [t.strip().lower() for t in (body.get("tags") or []) if t.strip()]
    result = supabase.table("contacts").update({"tags": tags}).eq("id", contact_id).eq("workspace_id", workspace_id).execute()
    return result.data[0] if result.data else {}


# ── WORKSPACE TAGS (catálogo de tags) ────────────────────────────────────────

@router.get("/workspace-tags")
async def list_workspace_tags(workspace_id: str):
    """Lista tags do workspace — do catálogo + descobertas nos contatos"""
    supabase = get_supabase()
    COL_TAGS = {'novo','contato','agendado','atendido','retorno','inativo'}
    
    # Tenta buscar da tabela de catálogo
    catalog = []
    try:
        r = supabase.table("workspace_tags").select("*").eq(
            "workspace_id", workspace_id).order("name").execute()
        catalog = r.data or []
    except Exception:
        pass

    # Descobre tags únicas nos contatos (fallback e complemento)
    contacts_r = supabase.table("contacts").select("tags").eq(
        "workspace_id", workspace_id).execute()
    discovered = set()
    for c in (contacts_r.data or []):
        for t in (c.get("tags") or []):
            if t and t not in COL_TAGS:
                discovered.add(t)

    # Merge — catálogo tem prioridade, descobertas complementam
    catalog_names = {t["name"] for t in catalog}
    for name in sorted(discovered):
        if name not in catalog_names:
            catalog.append({"id": name, "name": name, "color": "#7C3AED", "discovered": True})

    return catalog


@router.post("/workspace-tags")
async def create_workspace_tag(workspace_id: str, body: dict):
    """Cria uma nova tag no catálogo"""
    supabase = get_supabase()
    name = body.get("name", "").strip().lower()
    color = body.get("color", "#7C3AED")
    if not name:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Nome da tag é obrigatório")
    try:
        result = supabase.table("workspace_tags").insert({
            "workspace_id": workspace_id,
            "name": name,
            "color": color,
        }).execute()
        return result.data[0] if result.data else {}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Tag já existe ou erro ao criar")


@router.delete("/workspace-tags/{tag_id}")
async def delete_workspace_tag(tag_id: str, workspace_id: str):
    """Remove uma tag do catálogo"""
    supabase = get_supabase()
    supabase.table("workspace_tags").delete().eq(
        "id", tag_id
    ).eq("workspace_id", workspace_id).execute()
    return {"status": "deleted"}
