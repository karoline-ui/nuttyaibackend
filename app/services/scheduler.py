"""
app/services/scheduler.py
Scheduler para lembretes automáticos, campanhas agendadas e manutenção
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta, timezone
import asyncio

from app.core.config import settings
from app.core.database import get_supabase

scheduler = AsyncIOScheduler(
    timezone="America/Fortaleza",
    job_defaults={
        "coalesce": True,        # Se atrasou, executa só uma vez
        "max_instances": 1,      # Nunca duas execuções simultâneas do mesmo job
        "misfire_grace_time": 60 # Tolera até 60s de atraso antes de desistir
    }
)

async def start_scheduler():
    scheduler.add_job(
        process_pending_reminders,
        IntervalTrigger(seconds=settings.REMINDER_CHECK_INTERVAL),
        id="reminders", replace_existing=True,
    )
    scheduler.add_job(
        process_scheduled_campaigns,
        IntervalTrigger(seconds=settings.CAMPAIGN_CHECK_INTERVAL),
        id="campaigns", replace_existing=True,
    )
    scheduler.add_job(
        send_appointment_reminders,
        IntervalTrigger(minutes=5),
        id="apt_reminders", replace_existing=True,
    )
    scheduler.add_job(
        process_scheduled_flows,
        IntervalTrigger(minutes=1),
        id="scheduled_flows", replace_existing=True,
    )
    scheduler.start()
    print("✅ Scheduler started")

async def stop_scheduler():
    scheduler.shutdown()

async def process_pending_reminders():
    """Envia lembretes que chegaram no horário"""
    supabase = get_supabase()
    now = datetime.now().isoformat()

    pending = supabase.table("reminders").select("*").eq(
        "status", "pending"
    ).lte("scheduled_at", now).limit(50).execute()

    if not pending.data:
        return

    from app.services.whatsapp_service import whatsapp_client

    for reminder in pending.data:
        try:
            contact = supabase.table("contacts").select("phone").eq(
                "id", reminder["contact_id"]
            ).limit(1).execute()

            if contact.data and contact.data.get("phone"):
                await whatsapp_client.send_text(
                    phone=contact.data["phone"],
                    message=reminder["message"],
                    workspace_id=reminder["workspace_id"],
                )

            supabase.table("reminders").update({
                "status": "sent",
                "sent_at": datetime.now().isoformat(),
            }).eq("id", reminder["id"]).execute()

        except Exception as e:
            supabase.table("reminders").update({
                "status": "failed",
            }).eq("id", reminder["id"]).execute()
            print(f"Reminder failed {reminder['id']}: {e}")

async def process_scheduled_campaigns():
    """Lança campanhas que chegaram no horário agendado"""
    supabase = get_supabase()
    now = datetime.now().isoformat()

    scheduled = supabase.table("campaigns").select("*").eq(
        "status", "scheduled"
    ).lte("scheduled_at", now).limit(10).execute()

    if not scheduled.data:
        return

    for campaign in scheduled.data:
        try:
            from app.api.v1.campaigns import _execute_campaign

            contacts_result = supabase.table("contacts").select("id, phone").eq(
                "workspace_id", campaign["workspace_id"]
            ).eq("is_blocked", False).eq("opted_out", False).execute()

            contacts = contacts_result.data or []
            if campaign.get("target_tags"):
                contacts = [
                    c for c in contacts
                    if any(tag in (c.get("tags") or []) for tag in campaign["target_tags"])
                ]

            if contacts:
                recipients = [
                    {"campaign_id": campaign["id"], "contact_id": c["id"], "status": "queued"}
                    for c in contacts
                ]
                supabase.table("campaign_recipients").insert(recipients).execute()

                supabase.table("campaigns").update({
                    "status": "running",
                    "target_count": len(contacts),
                    "started_at": datetime.now().isoformat(),
                }).eq("id", campaign["id"]).execute()

                asyncio.create_task(_execute_campaign(
                    campaign_id=campaign["id"],
                    workspace_id=campaign["workspace_id"],
                    contacts=contacts,
                    campaign=campaign,
                ))
        except Exception as e:
            print(f"Campaign scheduled launch failed {campaign['id']}: {e}")

async def send_appointment_reminders():
    """
    Envia lembretes de agendamento automáticos
    Para consultas nas próximas 24h que ainda não receberam lembrete
    """
    supabase = get_supabase()
    now = datetime.now()
    in_24h = (now + timedelta(hours=24)).isoformat()
    in_23h = (now + timedelta(hours=23)).isoformat()

    appointments = supabase.table("appointments").select(
        "*, contacts(phone, name), workspaces(ai_persona)"
    ).gte("start_time", in_23h).lte("start_time", in_24h).eq(
        "status", "scheduled"
    ).eq("reminder_sent", False).execute()

    if not appointments.data:
        return

    from app.services.whatsapp_service import whatsapp_client

    for apt in appointments.data:
        try:
            contact = apt.get("contacts") or {}
            workspace = apt.get("workspaces") or {}
            phone = contact.get("phone")
            if not phone:
                continue

            persona = workspace.get("ai_persona", "Nutty")
            contact_name = contact.get("name", "")
            apt_time = datetime.fromisoformat(apt["start_time"])

            professional_line = f"👤 {apt['professional']}\n" if apt.get('professional') else ''
            greeting = f"Olá {contact_name}! 👋" if contact_name else "Olá! 👋"
            message = (
                f"{greeting}\n\n"
                f"*{persona}* aqui! Passando para lembrar do seu agendamento:\n\n"
                f"📅 *{apt['title']}*\n"
                f"🕐 {apt_time.strftime('%d/%m/%Y às %H:%M')}\n"
                f"{professional_line}\n"
                f"Para confirmar responda *SIM* ou para cancelar responda *NÃO*."
            )

            # Marca como enviado ANTES de enviar para evitar duplicação
            update_result = supabase.table("appointments").update({
                "reminder_sent": True,
                "reminder_at": datetime.now().isoformat(),
            }).eq("id", apt["id"]).eq("reminder_sent", False).execute()
            
            # Só envia se conseguiu marcar (evita race condition)
            if not update_result.data:
                continue

            await whatsapp_client.send_text(
                phone=phone,
                message=message,
                workspace_id=apt["workspace_id"],
            )

        except Exception as e:
            print(f"Apt reminder failed {apt['id']}: {e}")


async def process_flow_resumptions():
    """Retoma flows pausados por delay longo ou inatividade"""
    try:
        supabase = get_supabase()
        from datetime import timezone as _tz
        now = __import__("datetime").datetime.now(_tz.utc).isoformat()
        
        pending = supabase.table("flow_resumptions").select("*").eq(
            "status", "pending").lte("resume_at", now).limit(10).execute()
        
        for r in (pending.data or []):
            try:
                # Marca como processando
                supabase.table("flow_resumptions").update({"status": "processing"}).eq(
                    "id", r["id"]).execute()
                
                workspace_id = r["workspace_id"]
                flow_id = r["flow_id"]
                contact_phone = r["contact_phone"]
                resume_after = r["resume_after_node"]
                ctx_snapshot = r.get("context_snapshot", {})
                
                # Busca flow
                flow = supabase.table("flows").select("nodes, edges").eq(
                    "id", flow_id).limit(1).execute()
                if not flow.data:
                    continue
                
                nodes = flow.data[0].get("nodes", [])
                edges = flow.data[0].get("edges", [])
                
                # Encontra nó após o pausado
                next_edges = [e for e in edges if e.get("source") == resume_after]
                if not next_edges:
                    supabase.table("flow_resumptions").update({"status": "done"}).eq("id", r["id"]).execute()
                    continue
                
                next_node_id = next_edges[0].get("target")
                next_node = next((n for n in nodes if n["id"] == next_node_id), None)
                if not next_node:
                    continue
                
                # Busca contato
                contact_result = supabase.table("contacts").select("*").eq(
                    "workspace_id", workspace_id).eq("phone", contact_phone).limit(1).execute()
                contact = contact_result.data[0] if contact_result.data else {"phone": contact_phone}
                
                # Reconstrói contexto
                from app.api.v1.flows import run_flow
                context = {
                    "workspace_id": workspace_id,
                    "contact": contact,
                    "variables": ctx_snapshot.get("variables", {}),
                    "trigger_data": {"phone": contact_phone, "message": ""},
                }
                
                # Executa a partir do próximo nó
                from app.api.v1.flows import execute_node
                print(f"⏰ Retomando flow {flow_id} no nó {next_node_id} para {contact_phone}")
                
                current = next_node
                while current:
                    result = await execute_node(current, context, workspace_id, flow_id, nodes, edges)
                    if isinstance(result, dict) and result.get("_stop_flow"):
                        break
                    next_edges = [e for e in edges if e.get("source") == current["id"]]
                    if not next_edges:
                        break
                    next_id = next_edges[0].get("target")
                    current = next((n for n in nodes if n["id"] == next_id), None)
                
                supabase.table("flow_resumptions").update({"status": "done"}).eq("id", r["id"]).execute()
                
            except Exception as e:
                print(f"⚠️ Flow resumption error {r['id']}: {e}")
                supabase.table("flow_resumptions").update({"status": "error"}).eq("id", r["id"]).execute()
    except Exception as e:
        print(f"⚠️ process_flow_resumptions error: {e}")


async def process_scheduled_flows():
    """Executa flows com trigger=schedule cujo cron chegou no horário"""
    try:
        from croniter import croniter
    except ImportError:
        return  # pip install croniter
    supabase = get_supabase()

    flows = supabase.table("flows").select("*").eq(
        "is_active", True
    ).execute()

    if not flows.data:
        return

    br_tz = timezone(timedelta(hours=-3))
    now = datetime.now(timezone.utc).astimezone(br_tz)

    for flow in flows.data:
        nodes = flow.get("nodes", [])
        for node in nodes:
            nd = node.get("data", {})
            if nd.get("nodeType") != "trigger.schedule":
                continue
            cron_expr = nd.get("config", {}).get("cron", "")
            if not cron_expr:
                continue
            try:
                cron = croniter(cron_expr, now)
                prev = cron.get_prev(datetime)
                # Verifica se o cron bateu nos últimos 2 minutos
                # Normaliza ambos para naive datetime para comparação
                now_naive = now.replace(tzinfo=None)
                prev_naive = prev.replace(tzinfo=None) if prev.tzinfo else prev
                diff_seconds = (now_naive - prev_naive).total_seconds()
                if diff_seconds > 120:
                    continue

                # Busca todos os contatos ativos do workspace
                contacts = supabase.table("contacts").select(
                    "id, phone, name, tags"
                ).eq("workspace_id", flow["workspace_id"]).eq(
                    "opted_out", False
                ).limit(500).execute()

                from app.api.v1.flows import run_flow
                for contact in (contacts.data or []):
                    context = {
                        "trigger_data": {"type": "schedule", "cron": cron_expr},
                        "contact": contact,
                        "message": {"content": "", "type": "schedule"},
                        "variables": {},
                        "_simulating": False,
                    }
                    try:
                        await run_flow(flow["id"], flow["workspace_id"], context)
                    except Exception as e:
                        print(f"Scheduled flow error {flow['id']}: {e}")
            except Exception as e:
                print(f"Cron parse error: {e}")
