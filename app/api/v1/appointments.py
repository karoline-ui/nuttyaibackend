"""
app/api/v1/appointments.py
Gerenciamento de agenda com suporte a feriados brasileiros
"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional, List
from datetime import datetime, date
import json
import asyncio

from app.core.database import get_supabase

router = APIRouter()


@router.get("")
async def list_appointments(
    workspace_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    status: Optional[str] = None,
    professional: Optional[str] = None,
    contact_id: Optional[str] = None,
):
    """Lista agendamentos com filtros"""
    supabase = get_supabase()
    q = supabase.table("appointments").select(
        "*, contacts(name, phone)"
    ).eq("workspace_id", workspace_id)

    if start_date: q = q.gte("start_time", start_date)
    if end_date:   q = q.lte("start_time", end_date)
    if status:     q = q.eq("status", status)
    if professional: q = q.eq("professional", professional)
    if contact_id:   q = q.eq("contact_id", contact_id)

    result = q.order("start_time").execute()
    return result.data or []


@router.get("/calendar/{year}/{month}")
async def get_calendar_view(
    workspace_id: str,
    year: int,
    month: int,
):
    """Visão de calendário mensal com feriados"""
    from calendar import monthrange
    supabase = get_supabase()

    _, days_in_month = monthrange(year, month)
    start = f"{year}-{month:02d}-01"
    end   = f"{year}-{month:02d}-{days_in_month}"

    appointments = supabase.table("appointments").select(
        "*, contacts(name, phone)"
    ).eq("workspace_id", workspace_id).gte(
        "start_time", start + "T00:00:00"
    ).lte("start_time", end + "T23:59:59").neq(
        "status", "cancelled"
    ).order("start_time").execute()

    holidays = supabase.table("holidays").select("*").or_(
        f"workspace_id.eq.{workspace_id},workspace_id.is.null"
    ).execute()

    # Filtrar feriados do mês
    month_holidays = [
        h for h in (holidays.data or [])
        if h["date"] and int(h["date"][5:7]) == month
    ]

    from datetime import date as dateobj
    calendar_data = {}
    for i in range(1, days_in_month + 1):
        d = dateobj(year, month, i)
        calendar_data[d.isoformat()] = {
            "date": d.isoformat(),
            "appointments": [],
            "holidays": [],
            "is_weekend": d.weekday() >= 5,
        }

    for apt in (appointments.data or []):
        apt_date = apt["start_time"][:10]
        if apt_date in calendar_data:
            calendar_data[apt_date]["appointments"].append(apt)

    for hol in month_holidays:
        hol_date = hol["date"][:10] if hol["date"] else ""
        if hol_date in calendar_data:
            calendar_data[hol_date]["holidays"].append(hol)

    return {
        "year": year,
        "month": month,
        "days": list(calendar_data.values()),
    }


@router.get("/stream")
async def stream_appointments(workspace_id: str):
    """SSE para atualizações em tempo real da agenda"""
    async def event_generator():
        supabase = get_supabase()
        last_check = datetime.now().isoformat()
        
        yield f"data: {json.dumps({'type': 'connected'})}\n\n"
        
        while True:
            await asyncio.sleep(5)
            
            try:
                new_apts = supabase.table("appointments").select(
                    "*, contacts(name, phone)"
                ).eq("workspace_id", workspace_id).gt(
                    "updated_at", last_check
                ).execute()
                
                if new_apts.data:
                    for apt in new_apts.data:
                        yield f"data: {json.dumps({'type': 'appointment_update', 'data': apt})}\n\n"
                    last_check = datetime.now().isoformat()
                
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"
            except Exception as e:
                break
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@router.post("")
async def create_appointment(workspace_id: str, body: dict):
    """Cria agendamento manual"""
    supabase = get_supabase()
    
    result = supabase.table("appointments").insert({
        "workspace_id": workspace_id,
        **body,
        "source": "manual",
    }).execute()
    
    return result.data[0] if result.data else {}


@router.patch("/{appointment_id}")
async def update_appointment(
    appointment_id: str,
    workspace_id: str,
    body: dict,
):
    """Atualiza agendamento"""
    supabase = get_supabase()
    
    result = supabase.table("appointments").update(body).eq(
        "id", appointment_id
    ).eq("workspace_id", workspace_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return result.data[0]


@router.delete("/{appointment_id}")
async def delete_appointment(appointment_id: str, workspace_id: str):
    """Cancela agendamento"""
    supabase = get_supabase()
    
    supabase.table("appointments").update({
        "status": "cancelled"
    }).eq("id", appointment_id).eq("workspace_id", workspace_id).execute()
    
    return {"status": "cancelled"}


@router.get("/holidays")
async def get_holidays(
    workspace_id: str,
    year: Optional[int] = None,
):
    """Lista feriados nacionais + do workspace"""
    supabase = get_supabase()
    result = supabase.table("holidays").select("*").or_(
        f"workspace_id.eq.{workspace_id},workspace_id.is.null"
    ).order("date").execute()

    data = result.data or []
    if year:
        data = [h for h in data if h.get("date", "").startswith(str(year))]
    return data


@router.post("/holidays/custom")
async def add_custom_holiday(workspace_id: str, body: dict):
    """Adiciona feriado customizado para o workspace"""
    supabase = get_supabase()
    
    result = supabase.table("holidays").insert({
        "workspace_id": workspace_id,
        "type": "custom",
        **body,
    }).execute()
    
    return result.data[0] if result.data else {}