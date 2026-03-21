"""
app/api/v1/campaigns.py - Campanhas de envio em massa com anti-ban
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from datetime import datetime
import asyncio

from app.core.database import get_supabase

router = APIRouter()


@router.get("")
async def list_campaigns(workspace_id: str):
    supabase = get_supabase()
    result = supabase.table("campaigns").select("*").eq(
        "workspace_id", workspace_id
    ).order("created_at", desc=True).execute()
    return result.data or []


@router.post("")
async def create_campaign(workspace_id: str, body: dict):
    supabase = get_supabase()
    result = supabase.table("campaigns").insert({
        "workspace_id": workspace_id,
        "status": "draft",
        **body,
    }).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Erro ao criar campanha")
    return result.data[0]


@router.patch("/{campaign_id}")
async def update_campaign(campaign_id: str, workspace_id: str, body: dict):
    supabase = get_supabase()
    camp = supabase.table("campaigns").select("status").eq(
        "id", campaign_id).eq("workspace_id", workspace_id).single().execute()
    if not camp.data:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    if camp.data["status"] not in ["draft", "scheduled"]:
        raise HTTPException(status_code=400, detail="Só é possível editar campanhas em rascunho ou agendadas")
    result = supabase.table("campaigns").update(body).eq("id", campaign_id).execute()
    return result.data[0] if result.data else {}


@router.post("/{campaign_id}/launch")
async def launch_campaign(
    campaign_id: str,
    workspace_id: str,
    background_tasks: BackgroundTasks,
):
    """Inicia execução da campanha"""
    supabase = get_supabase()

    # Buscar campanha
    campaign = supabase.table("campaigns").select("*").eq(
        "id", campaign_id
    ).eq("workspace_id", workspace_id).execute()

    if not campaign.data:
        raise HTTPException(status_code=404, detail=f"Campanha {campaign_id} não encontrada")

    camp = campaign.data[0]

    if camp["status"] not in ["draft", "scheduled"]:
        raise HTTPException(status_code=400, detail=f"Campanha não pode ser lançada (status: {camp['status']})")

    # Buscar contatos
    target_tags = camp.get("target_tags") or []
    contacts_q = supabase.table("contacts").select("id, phone, name, tags").eq(
        "workspace_id", workspace_id
    ).eq("is_blocked", False).eq("opted_out", False)

    contacts_result = contacts_q.execute()
    contacts = contacts_result.data or []

    # Filtrar por tags se especificado
    if target_tags:
        contacts = [
            c for c in contacts
            if any(tag in (c.get("tags") or []) for tag in target_tags)
        ]

    if not contacts:
        raise HTTPException(
            status_code=400,
            detail="Nenhum contato encontrado para esta campanha. Verifique as tags ou cadastre contatos."
        )

    # Criar recipients
    recipients = [
        {"campaign_id": campaign_id, "contact_id": c["id"], "status": "queued"}
        for c in contacts
    ]
    supabase.table("campaign_recipients").insert(recipients).execute()

    # Atualizar status
    supabase.table("campaigns").update({
        "status": "running",
        "target_count": len(contacts),
        "started_at": datetime.now().isoformat(),
    }).eq("id", campaign_id).execute()

    # Executar em background
    background_tasks.add_task(_execute_campaign, campaign_id, workspace_id, contacts, camp)

    return {
        "status": "launched",
        "target_count": len(contacts),
        "message": f"Campanha iniciada para {len(contacts)} contatos"
    }


async def _execute_campaign(campaign_id: str, workspace_id: str, contacts: list, campaign: dict):
    """Envia mensagens com delay anti-ban"""
    supabase = get_supabase()
    sent = 0
    failed = 0

    for i, contact in enumerate(contacts):
        try:
            from app.services.whatsapp_service import whatsapp_client
            message = campaign["message_template"].replace(
                "{{nome}}", contact.get("name") or contact.get("phone") or ""
            )
            # Envia mídia se configurada
            media_file_id = campaign.get("media_file_id")
            if media_file_id:
                # Busca URL da mídia
                mf = supabase.table("media_files").select("public_url, mime_type, file_name").eq(
                    "id", media_file_id).limit(1).execute()
                if mf.data:
                    mfile = mf.data[0]
                    mime = mfile.get("mime_type", "")
                    url = mfile.get("public_url", "")
                    # URL relativa → URL absoluta
                    if url.startswith("/"):
                        url = "https://nuttyaibackend-897373535500.southamerica-east1.run.app" + url
                    if "image" in mime:
                        await whatsapp_client.send_image(contact["phone"], url, message, workspace_id)
                    else:
                        await whatsapp_client.send_text(contact["phone"], message, workspace_id)
                else:
                    await whatsapp_client.send_text(contact["phone"], message, workspace_id)
            else:
                await whatsapp_client.send_text(
                    phone=contact["phone"],
                    message=message,
                    workspace_id=workspace_id,
                )
            sent += 1

            # Atualizar recipient
            supabase.table("campaign_recipients").update({
                "status": "sent", "sent_at": datetime.now().isoformat()
            }).eq("campaign_id", campaign_id).eq("contact_id", contact["id"]).execute()

            # Tag automática no contato
            try:
                tag_name = "campanha_" + campaign.get("name", "").lower().replace(" ", "_")[:30]
                ct = supabase.table("contacts").select("tags").eq("id", contact["id"]).limit(1).execute()
                current_tags = (ct.data[0] if ct.data else {}).get("tags") or []
                if tag_name not in current_tags:
                    supabase.table("contacts").update({
                        "tags": current_tags + [tag_name]
                    }).eq("id", contact["id"]).execute()
            except Exception:
                pass

        except Exception as e:
            failed += 1
            supabase.table("campaign_recipients").update({
                "status": "failed", "error": str(e)[:200]
            }).eq("campaign_id", campaign_id).eq("contact_id", contact["id"]).execute()

        # Delay anti-ban
        delay_ms = campaign.get("delay_between_ms", 3000)
        if i < len(contacts) - 1:
            await asyncio.sleep(delay_ms / 1000)

        # Atualizar progresso a cada 10 enviados
        if (i + 1) % 10 == 0:
            supabase.table("campaigns").update({
                "sent_count": sent, "failed_count": failed
            }).eq("id", campaign_id).execute()

    # Finalizar
    supabase.table("campaigns").update({
        "status": "completed",
        "sent_count": sent,
        "failed_count": failed,
        "finished_at": datetime.now().isoformat(),
    }).eq("id", campaign_id).execute()


@router.get("/{campaign_id}/stats")
async def get_campaign_stats(campaign_id: str, workspace_id: str):
    supabase = get_supabase()
    camp = supabase.table("campaigns").select("*").eq(
        "id", campaign_id).eq("workspace_id", workspace_id).single().execute()
    if not camp.data:
        raise HTTPException(status_code=404, detail="Campanha não encontrada")
    return camp.data


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: str, workspace_id: str):
    supabase = get_supabase()
    supabase.table("campaigns").delete().eq("id", campaign_id).eq("workspace_id", workspace_id).execute()
    return {"status": "deleted"}
