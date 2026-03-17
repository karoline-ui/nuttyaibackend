"""
app/api/v1/dashboard.py — Métricas do dashboard
"""
from fastapi import APIRouter
from app.core.database import get_supabase
from datetime import datetime, timedelta

router = APIRouter()

@router.get("")
async def get_dashboard_stats(workspace_id: str):
    """Retorna métricas para o dashboard usando Supabase client"""
    supabase = get_supabase()
    today = datetime.now().date().isoformat()
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()

    # Conversas hoje
    convs_today = supabase.table("conversations").select(
        "id", count="exact"
    ).eq("workspace_id", workspace_id).gte(
        "created_at", today
    ).execute()

    # Agendamentos hoje
    apts_today = supabase.table("appointments").select(
        "id", count="exact"
    ).eq("workspace_id", workspace_id).gte(
        "start_time", today + "T00:00:00"
    ).lte("start_time", today + "T23:59:59").neq(
        "status", "cancelled"
    ).execute()

    # Contatos ativos (últimos 7 dias)
    seven_days_ago = (datetime.now() - timedelta(days=7)).isoformat()
    active_contacts = supabase.table("conversations").select(
        "contact_id"
    ).eq("workspace_id", workspace_id).gte(
        "last_message_at", seven_days_ago
    ).execute()

    # Mensagens por hora (últimas 24h) — simplificado
    msgs_24h = supabase.table("messages").select(
        "created_at"
    ).eq("workspace_id", workspace_id).gte(
        "created_at", (datetime.now() - timedelta(hours=24)).isoformat()
    ).execute()

    # Agrupar por hora
    hourly_map: dict = {}
    for msg in (msgs_24h.data or []):
        try:
            hour = int(msg["created_at"][11:13])
            hourly_map[hour] = hourly_map.get(hour, 0) + 1
        except:
            pass
    hourly_messages = [
        {"hour": f"{h:02d}h", "count": hourly_map.get(h, 0)}
        for h in range(24)
    ]

    # Status IA nas conversas abertas
    ai_status_data = supabase.table("conversations").select(
        "ai_status"
    ).eq("workspace_id", workspace_id).eq("status", "open").execute()

    ai_counts: dict = {}
    for c in (ai_status_data.data or []):
        s = c.get("ai_status", "paused")
        ai_counts[s] = ai_counts.get(s, 0) + 1

    ai_status_pie = [
        {"name": k, "value": v} for k, v in ai_counts.items()
    ] or [{"name": "active", "value": 0}]

    return {
        "conversations_today": convs_today.count or 0,
        "conversations_change": 0,
        "appointments_today": apts_today.count or 0,
        "appointments_change": 0,
        "active_contacts": len(set(
            c["contact_id"] for c in (active_contacts.data or [])
        )),
        "response_rate": 0,
        "response_rate_change": 0,
        "hourly_messages": hourly_messages,
        "ai_status_pie": ai_status_pie,
    }