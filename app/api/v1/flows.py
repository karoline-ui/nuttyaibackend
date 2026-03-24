"""
app/api/v1/flows.py
Motor de automação visual (estilo n8n)
Suporta: triggers, condições, ações, delays, loops
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional, Dict, Any, List
from datetime import datetime
import asyncio
import httpx
import json

from app.core.database import get_supabase
from app.services.whatsapp_service import whatsapp_client

router = APIRouter()


# ══════════════════════════════════════════════
# NODE TYPES disponíveis
# ══════════════════════════════════════════════
AVAILABLE_NODES = {
    # TRIGGERS
    "trigger.message_received":    {"label": "Mensagem Recebida",     "category": "trigger", "icon": "MessageCircle"},
    "trigger.keyword":             {"label": "Palavra-chave Exata",   "category": "trigger", "icon": "Search"},
    "trigger.button_clicked":      {"label": "Botão Clicado",         "category": "trigger", "icon": "MousePointer"},
    "trigger.new_contact":         {"label": "Novo Contato",          "category": "trigger", "icon": "UserPlus"},
    "trigger.tag_added":           {"label": "Tag Adicionada",        "category": "trigger", "icon": "Tag"},
    "trigger.appointment_created": {"label": "Agendamento Criado",    "category": "trigger", "icon": "Calendar"},
    "trigger.schedule":            {"label": "Agendado (Cron)",       "category": "trigger", "icon": "Timer"},
    "trigger.webhook":             {"label": "Webhook Recebido",      "category": "trigger", "icon": "Zap"},
    # LÓGICA
    "condition.if":                {"label": "Condição SE",           "category": "logic",   "icon": "GitBranch"},
    "condition.switch":            {"label": "Switch / Router",       "category": "logic",   "icon": "Shuffle"},
    "condition.delay":             {"label": "Aguardar",              "category": "logic",   "icon": "Timer"},
    "condition.inactivity":        {"label": "Inatividade",           "category": "logic",   "icon": "Clock"},
    "condition.time_check":        {"label": "Verificar Horário",     "category": "logic",   "icon": "Clock"},
    "condition.loop":              {"label": "Loop / Repetição",      "category": "logic",   "icon": "Repeat"},
    "condition.ab_test":           {"label": "Teste A/B",             "category": "logic",   "icon": "BarChart2"},
    "condition.counter":           {"label": "Contador",              "category": "logic",   "icon": "Hash"},
    "condition.set_variable":      {"label": "Definir Variável",      "category": "logic",   "icon": "Database"},
    "condition.subflow":           {"label": "Executar Subflow",      "category": "logic",   "icon": "GitBranch"},
    # WHATSAPP
    "action.send_text":            {"label": "Enviar Texto",          "category": "whatsapp","icon": "MessageCircle"},
    "action.send_image":           {"label": "Enviar Imagem",         "category": "whatsapp","icon": "FileText"},
    "action.send_document":        {"label": "Enviar Documento",      "category": "whatsapp","icon": "FileText"},
    "action.send_audio":           {"label": "Enviar Áudio",          "category": "whatsapp","icon": "Mic"},
    "action.send_buttons":         {"label": "Botões Rápidos",        "category": "whatsapp","icon": "MousePointer"},
    "action.send_list":            {"label": "Menu de Opções",        "category": "whatsapp","icon": "List"},
    "action.send_location":        {"label": "Enviar Localização",    "category": "whatsapp","icon": "Globe"},
    "action.wait_reply":           {"label": "Aguardar Resposta",     "category": "whatsapp","icon": "Clock"},
    "action.collect_data":         {"label": "Coletar Dado",          "category": "whatsapp","icon": "Database"},
    "action.check_read":           {"label": "Verificar Leitura",     "category": "whatsapp","icon": "CheckSquare"},
    # IA
    "action.ai_respond":           {"label": "IA Responde",           "category": "ai",      "icon": "Bot"},
    "action.ai_classify":          {"label": "IA Classifica",         "category": "ai",      "icon": "Tag"},
    "action.ai_extract":           {"label": "Extrair Entidade",      "category": "ai",      "icon": "Search"},
    "action.ai_summarize":         {"label": "Resumir Conversa",      "category": "ai",      "icon": "FileText"},
    "action.ai_sentiment":         {"label": "Analisar Sentimento",   "category": "ai",      "icon": "TrendingUp"},
    "action.ai_reactivate":        {"label": "Reativar IA",           "category": "ai",      "icon": "Bot"},
    "action.ai_pause":             {"label": "Pausar IA",             "category": "ai",      "icon": "ToggleLeft"},
    # AGENDA
    "action.create_appointment":   {"label": "Criar Agendamento",     "category": "calendar","icon": "Calendar"},
    "action.cancel_appointment":   {"label": "Cancelar Agendamento",  "category": "calendar","icon": "Calendar"},
    "action.check_availability":   {"label": "Verificar Disponib.",   "category": "calendar","icon": "Clock"},
    "action.send_reminder":        {"label": "Enviar Lembrete",       "category": "calendar","icon": "Bell"},
    "action.confirm_appointment":  {"label": "Confirmar Consulta",    "category": "calendar","icon": "CalendarCheck"},
    # CONTATOS
    "action.update_contact":       {"label": "Atualizar Contato",     "category": "contact", "icon": "User"},
    "action.add_tag":              {"label": "Adicionar Tag",         "category": "contact", "icon": "Tag"},
    "action.remove_tag":           {"label": "Remover Tag",           "category": "contact", "icon": "Tag"},
    "action.create_contact":       {"label": "Criar Contato",         "category": "contact", "icon": "UserPlus"},
    "action.score_contact":        {"label": "Pontuar Contato",       "category": "contact", "icon": "Star"},
    "action.block_contact":        {"label": "Bloquear Contato",      "category": "contact", "icon": "Shield"},
    "action.notify_team":          {"label": "Notificar Equipe",      "category": "contact", "icon": "Phone"},
    # INTEGRAÇÕES
    "action.http_request":         {"label": "Requisição HTTP",       "category": "integration","icon": "Globe"},
    "action.send_email":           {"label": "Enviar Email",          "category": "integration","icon": "Mail"},
    "action.webhook_send":         {"label": "Enviar Webhook",        "category": "integration","icon": "Zap"},
}


@router.get("/node-types")
async def get_node_types():
    """Retorna todos os tipos de nós disponíveis — nunca muda, cache longo"""
    return AVAILABLE_NODES


@router.get("")
async def list_flows(workspace_id: str):
    from app.core.cache import get as c_get, set as c_set
    ck = f"flows:{workspace_id}"
    cached = c_get(ck)
    if cached is not None:
        return cached
    supabase = get_supabase()
    result = supabase.table("flows").select("*").eq(
        "workspace_id", workspace_id
    ).order("created_at", desc=True).execute()
    
    # Adiciona run_count para cada flow
    flows = result.data or []
    for flow in flows:
        try:
            cnt = supabase.table("flow_executions").select("id", count="exact").eq(
                "flow_id", flow["id"]).execute()
            flow["run_count"] = cnt.count or 0
        except Exception:
            flow["run_count"] = 0
    
    c_set(ck, flows, ttl=20)
    return flows


@router.post("")
async def create_flow(workspace_id: str, body: dict):
    """Cria um novo flow"""
    supabase = get_supabase()
    
    result = supabase.table("flows").insert({
        "workspace_id": workspace_id,
        "name": body.get("name", "Novo Flow"),
        "description": body.get("description", ""),
        "trigger": body.get("trigger", "message_received"),
        "trigger_config": body.get("trigger_config", {}),
        "nodes": body.get("nodes", []),
        "edges": body.get("edges", []),
        "is_active": False,
    }).execute()
    
    return result.data[0] if result.data else {}


@router.get("/{flow_id}")
async def get_flow(flow_id: str, workspace_id: str):
    supabase = get_supabase()
    result = supabase.table("flows").select("*").eq(
        "id", flow_id
    ).eq("workspace_id", workspace_id).limit(1).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Flow not found")
    return result.data[0]


@router.put("/{flow_id}")
async def update_flow(flow_id: str, workspace_id: str, body: dict):
    """Salva/atualiza flow (nodes + edges)"""
    supabase = get_supabase()

    # Buscar trigger atual se não enviado
    current = supabase.table("flows").select("trigger").eq(
        "id", flow_id).eq("workspace_id", workspace_id).limit(1).execute()
    current_trigger = (current.data[0] if current.data else {}).get("trigger", "message_received") if current.data else "message_received"

    update_data = {
        "name": body.get("name") or "Flow",
        "nodes": body.get("nodes", []),
        "edges": body.get("edges", []),
        "trigger": body.get("trigger") or current_trigger,
        "updated_at": datetime.now().isoformat(),
    }
    if body.get("description") is not None:
        update_data["description"] = body["description"]

    result = supabase.table("flows").update(update_data).eq(
        "id", flow_id).eq("workspace_id", workspace_id).execute()

    from app.core.cache import delete_prefix
    delete_prefix(f"flows:{workspace_id}")
    return result.data[0] if result.data else {}


@router.patch("/{flow_id}/toggle")
async def toggle_flow(flow_id: str, workspace_id: str, is_active: bool):
    """Ativa ou desativa um flow"""
    supabase = get_supabase()
    supabase.table("flows").update({
        "is_active": is_active
    }).eq("id", flow_id).eq("workspace_id", workspace_id).execute()
    return {"status": "updated", "is_active": is_active}


@router.delete("/{flow_id}")
async def delete_flow(flow_id: str, workspace_id: str):
    """Exclui um flow permanentemente"""
    from app.core.cache import delete_prefix
    supabase = get_supabase()
    # Verifica se o flow pertence ao workspace antes de deletar
    flow = supabase.table("flows").select("id").eq(
        "id", flow_id
    ).eq("workspace_id", workspace_id).limit(1).execute()
    if not flow.data:
        raise HTTPException(status_code=404, detail="Flow não encontrado")
    supabase.table("flows").delete().eq("id", flow_id).eq(
        "workspace_id", workspace_id
    ).execute()
    delete_prefix(f"flows:{workspace_id}")
    return {"status": "deleted", "id": flow_id}


async def execute_flow_manually(
    flow_id: str,
    workspace_id: str,
    background_tasks: BackgroundTasks,
    trigger_data: dict = {},
):
    """Executa um flow manualmente para teste"""
    background_tasks.add_task(
        run_flow,
        flow_id=flow_id,
        workspace_id=workspace_id,
        trigger_data=trigger_data,
    )
    return {"status": "started"}


@router.post("/{flow_id}/simulate")
async def simulate_flow(flow_id: str, workspace_id: str, body: dict = {}):
    """
    Simula o flow passo a passo e retorna log detalhado de cada nó.
    Não envia mensagens reais — apenas testa a lógica.
    """
    supabase = get_supabase()

    flow = supabase.table("flows").select("*").eq("id", flow_id).eq("workspace_id", workspace_id).limit(1).execute()
    if not flow.data:
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    nodes = (flow.data[0] if flow.data else {}).get("nodes", [])
    edges = (flow.data[0] if flow.data else {}).get("edges", [])

    if not nodes:
        return {"steps": [], "error": "Flow sem nós. Adicione pelo menos um gatilho e uma ação."}

    # Contexto de simulação com dados fictícios
    test_message = body.get("test_message", "Olá! Quero marcar uma consulta.")
    test_contact = body.get("contact", {
        "name": "Maria Teste",
        "phone": "5579999990000",
        "tags": body.get("test_tags", ["novo"]),
        "email": "teste@email.com",
    })

    # Histórico da sessão de simulação — frontend envia para manter contexto entre mensagens
    session_history = body.get("session_history", [])

    context = {
        "workspace_id": workspace_id,
        "contact": test_contact,
        "message": {"content": test_message, "type": "text"},
        "variables": {},
        "_simulating": True,
        "_sim_history": session_history,  # histórico acumulado da sessão
    }

    steps = []
    start_time = datetime.now()

    # Encontrar trigger — prioriza chat_node_id se fornecido
    chat_node_id = body.get("chat_node_id")
    if chat_node_id:
        # Começa pelo nó de chat e segue suas edges
        start_node = next((n for n in nodes if n["id"] == chat_node_id), None)
        if start_node:
            # Pega o próximo nó conectado ao chat (o que ele dispara)
            next_edges = [e for e in edges if e.get("source") == chat_node_id]
            next_id = next_edges[0].get("target") if next_edges else None
            current_node = next((n for n in nodes if n["id"] == next_id), None) if next_id else None
            if not current_node:
                # Sem conexão — usa o primeiro trigger não-chat
                trigger_nodes = [n for n in nodes if n.get("data", {}).get("nodeType", "").startswith("trigger.") and n["id"] != chat_node_id]
                current_node = trigger_nodes[0] if trigger_nodes else None
        else:
            current_node = None
    else:
        trigger_nodes = [n for n in nodes if n.get("data", {}).get("nodeType", "").startswith("trigger.") and n.get("data", {}).get("nodeType") != "trigger.chat_test"]
        if not trigger_nodes:
            # fallback — qualquer trigger
            trigger_nodes = [n for n in nodes if n.get("data", {}).get("nodeType", "").startswith("trigger.")]
        if not trigger_nodes:
            return {
                "steps": [],
                "error": "Nenhum nó de GATILHO encontrado. Todo flow precisa começar com um gatilho.",
                "suggestion": "Arraste um nó de Gatilho para o início do flow."
            }
        current_node = trigger_nodes[0]
    visited = set()

    while current_node and len(steps) < 30:
        node_id = current_node.get("id")
        node_data = current_node.get("data", {})
        node_type = node_data.get("nodeType", "unknown")
        node_label = node_data.get("label", node_type)
        config = node_data.get("config", {})

        if node_id in visited:
            steps.append({
                "node_id": node_id, "node_type": node_type, "label": node_label,
                "status": "skipped", "message": "Nó já visitado — loop detectado",
                "duration_ms": 0,
            })
            break
        visited.add(node_id)

        t0 = datetime.now()
        step = {
            "node_id": node_id,
            "node_type": node_type,
            "label": node_label,
            "config": config,
        }

        try:
            # ── Simular cada tipo de nó ──────────────────────────
            if node_type.startswith("trigger."):
                step["status"] = "ok"
                step["message"] = f"✅ Gatilho ativado com mensagem: \"{test_message}\""
                step["output"] = {"contact": test_contact, "message": test_message}

            elif node_type == "action.ai_respond":
                ctx = config.get("context_override", "")
                # Busca nome da persona do workspace
                try:
                    ws_data = supabase.table("workspaces").select("ai_persona").eq("id", workspace_id).limit(1).execute()
                    persona_name = (ws_data.data[0] if ws_data.data else {}).get("ai_persona", "IA") if ws_data.data else "IA"
                except Exception:
                    persona_name = "IA"
                ai_response_text = ""
                try:
                    from app.services.ai_service import process_message
                    sim_history = context.get("_sim_history", [])
                    # Adiciona contexto de persona ao histórico para memória placebo
                    if not sim_history:
                        try:
                            ws_instructions = supabase.table("workspaces").select(
                                "ai_instructions,ai_persona"
                            ).eq("id", workspace_id).limit(1).execute()
                            if ws_instructions.data and (ws_instructions.data[0] if ws_instructions.data else {}).get("ai_instructions"):
                                pass  # system prompt já é injetado pelo process_message
                        except Exception:
                            pass
                    ai_result = await process_message(
                        workspace_id=workspace_id,
                        contact_phone=test_contact["phone"],
                        conversation_id=f"simulate_{workspace_id}",
                        message_content=test_message,
                        conversation_history=sim_history,
                    )
                    ai_response_text = ai_result.get("response", "")
                    # Acumula histórico para memória entre mensagens
                    context.setdefault("_sim_history", [])
                    context["_sim_history"].append({"content": test_message, "direction": "inbound"})
                    context["_sim_history"].append({"content": ai_response_text, "direction": "outbound"})
                    # Limita histórico a 20 mensagens para não exceder contexto
                    if len(context["_sim_history"]) > 20:
                        context["_sim_history"] = context["_sim_history"][-20:]
                    if ctx:
                        ai_response_text = f"[ctx: {ctx[:40]}] {ai_response_text}"
                except Exception as ai_err:
                    ai_response_text = f"(IA indisponível: {str(ai_err)[:60]})"
                step["status"] = "ok"
                step["message"] = f"🤖 {persona_name}: {ai_response_text[:120]}"
                step["output"] = {"preview": ai_response_text, "response": ai_response_text}

            elif node_type == "action.ai_classify":
                cats = config.get("categories", "")
                field = config.get("output_field", "classification")
                cats_list = [c.strip() for c in str(cats).split(",") if c.strip()]
                simulated = cats_list[0] if cats_list else "categoria_1"
                context["variables"][field] = simulated
                step["status"] = "ok"
                step["message"] = f"🏷️ IA classificaria \"{test_message}\" em uma das categorias: {cats}\nResultado simulado: {simulated} → salvo em {field}"
                step["output"] = {field: simulated}

            elif node_type == "action.send_text":
                msg = config.get("message", "")
                preview = msg.replace("{{contact.name}}", test_contact["name"]).replace("{{contact.phone}}", test_contact["phone"])[:200]
                step["status"] = "ok"
                step["message"] = f"💬 Mensagem SERIA enviada para {test_contact['name']} ({test_contact['phone']}):\n{preview}"
                step["output"] = {"to": test_contact["phone"], "preview": preview}

            elif node_type == "action.add_tag":
                tag = config.get("tag", "")
                if not tag:
                    step["status"] = "warning"
                    step["message"] = "⚠️ Tag não configurada — defina o nome da tag no painel de configuração deste nó"
                else:
                    step["status"] = "ok"
                    step["message"] = f"🏷️ Tag \"{tag}\" seria adicionada ao contato {test_contact['name']}"
                    if tag not in context["contact"].get("tags", []):
                        context["contact"].setdefault("tags", []).append(tag)
                step["output"] = {"tag": tag, "contact_tags": context["contact"].get("tags", [])}

            elif node_type == "action.notify_team":
                phone = config.get("phone", "")
                msg = config.get("message", "")
                if not phone:
                    step["status"] = "warning"
                    step["message"] = "⚠️ Telefone da equipe não configurado"
                else:
                    preview = msg.replace("{{contact.name}}", test_contact["name"])[:150]
                    step["status"] = "ok"
                    step["message"] = f"📞 Notificação SERIA enviada para {phone}:\n{preview}"

            elif node_type == "condition.if":
                field = config.get("field", "")
                operator = config.get("operator", "equals")
                value = config.get("value", "")
                # Simular resultado
                field_val = str(context.get("variables", {}).get(field, context.get("contact", {}).get(field.replace("contact.", ""), "")))
                if operator == "equals":
                    result_bool = field_val == value
                elif operator == "contains":
                    result_bool = value.lower() in field_val.lower()
                else:
                    result_bool = True  # Simular como verdadeiro
                context["variables"]["_last_condition"] = result_bool
                step["status"] = "ok"
                step["message"] = f"🔀 Condição: {field} {operator} '{value}'\nValor encontrado: '{field_val}'\nResultado: {'✅ VERDADEIRO → caminho SIM' if result_bool else '❌ FALSO → caminho NÃO'}"
                step["output"] = {"result": result_bool, "branch": "yes" if result_bool else "no"}

            elif node_type == "condition.switch":
                field = config.get("field", "")
                field_val = str(context.get("variables", {}).get(field, ""))
                cases = []
                for i in range(1, 4):
                    cv = config.get(f"case{i}_value", "")
                    cl = config.get(f"case{i}_label", "")
                    if cv:
                        match = field_val == cv or field_val.lower() == cv.lower()
                        cases.append(f"  Caso {i}: '{cv}' → {cl} {'← MATCH ✅' if match else ''}")
                default = config.get("default_label", "Padrão")
                step["status"] = "ok"
                step["message"] = f"🔀 Switch no campo '{field}' (valor atual: '{field_val or 'vazio'}'):\n" + "\n".join(cases) + f"\n  Padrão: {default}"
                step["output"] = {"field": field, "value": field_val, "cases": cases}

            elif node_type == "condition.delay":
                dur = config.get("duration", "?")
                unit = config.get("unit", "minutos")
                step["status"] = "ok"
                step["message"] = f"⏱️ Flow aguardaria {dur} {unit} antes de continuar\n(Em simulação, o delay é ignorado)"

            elif node_type == "condition.inactivity":
                dur = config.get("duration", "?")
                unit = config.get("unit", "minutos")
                action = config.get("action", "")
                step["status"] = "ok"
                step["message"] = f"👻 Detectaria inatividade após {dur} {unit}\nAção configurada: {action or 'não definida'}"

            elif node_type == "condition.time_check":
                from datetime import timezone as _tz, timedelta as _td
                TZ_OFFSETS = {
                    "America/Fortaleza": -3, "America/Recife": -3,
                    "America/Sao_Paulo": -3, "America/Belem": -3,
                    "America/Manaus": -4, "America/Porto_Velho": -4,
                    "America/Rio_Branco": -5, "America/Noronha": -2,
                }
                tz_name = config.get("timezone") or "America/Fortaleza"
                offset = TZ_OFFSETS.get(tz_name, -3)
                br_tz = _tz(_td(hours=offset))
                now = datetime.now(_tz.utc).astimezone(br_tz)
                start_h, start_m = [int(x) for x in (config.get("start_time", "08:00") + ":00").split(":")[:2]]
                end_h, end_m = [int(x) for x in (config.get("end_time", "18:00") + ":00").split(":")[:2]]
                start_mins = start_h * 60 + start_m
                end_mins = end_h * 60 + end_m
                cur_mins = now.hour * 60 + now.minute
                days_cfg = config.get("days", "mon,tue,wed,thu,fri").split(",")
                day_map = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
                in_hours = start_mins <= cur_mins <= end_mins
                in_days = any(day_map.get(d.strip()) == now.weekday() for d in days_cfg)
                result_bool = in_hours and in_days
                context["variables"]["_in_business_hours"] = result_bool
                step["status"] = "ok"
                step["message"] = (
                    f"✅ DENTRO do horário comercial ({now.strftime('%H:%M')} UTC{offset:+d})"
                    if result_bool else
                    f"⏰ FORA do horário ({now.strftime('%H:%M')} UTC{offset:+d}) → caminho 'Fora'"
                )
                step["output"] = {"result": result_bool, "branch": "inside" if result_bool else "outside",
                                  "current_time": now.strftime("%H:%M"), "timezone": tz_name}

            elif node_type == "action.ai_reactivate":
                msg = config.get("message", "")
                step["status"] = "ok"
                step["message"] = f"▶️ IA seria reativada na conversa" + (f"\nMensagem de retorno: {msg}" if msg else "")

            elif node_type == "action.ai_pause":
                step["status"] = "ok"
                step["message"] = "⏸️ IA seria pausada — conversa ficaria aguardando atendimento humano"

            elif node_type == "action.update_contact":
                field = config.get("field", "")
                value = config.get("value", "")
                step["status"] = "ok"
                step["message"] = f"✏️ Campo '{field}' do contato seria atualizado para: '{value}'"

            elif node_type in ["action.send_image", "action.send_document", "action.send_audio"]:
                tipos = {"action.send_image": "🖼️ Imagem", "action.send_document": "📄 Documento", "action.send_audio": "🔊 Áudio"}
                step["status"] = "ok"
                step["message"] = f"{tipos[node_type]} seria enviado para {test_contact['name']}"

            elif node_type == "action.create_appointment":
                step["status"] = "ok"
                step["message"] = f"📅 Agendamento seria criado para {test_contact['name']}"

            elif node_type == "action.http_request":
                url = config.get("url", "")
                method = config.get("method", "GET")
                if not url:
                    step["status"] = "warning"
                    step["message"] = "⚠️ URL não configurada — defina a URL da requisição HTTP"
                else:
                    step["status"] = "ok"
                    step["message"] = f"🌐 Requisição {method} seria feita para: {url}"

            else:
                step["status"] = "ok"
                step["message"] = f"✅ Nó '{node_label}' seria executado"

        except Exception as e:
            step["status"] = "error"
            step["message"] = f"❌ Erro: {str(e)}"

        step["duration_ms"] = int((datetime.now() - t0).total_seconds() * 1000)
        steps.append(step)

        # Próximo nó — respeita condições de roteamento
        next_edges = [e for e in edges if e.get("source") == node_id]
        next_id = None

        if node_type == "condition.time_check":
            # Roteia por label da edge: "Dentro" ou "Fora"
            in_hours = context["variables"].get("_in_business_hours", True)
            target_label = "Dentro" if in_hours else "Fora"
            for e in next_edges:
                lbl = (e.get("label") or "").strip()
                if lbl.lower() == target_label.lower() or (in_hours and lbl == "") or (not next_id and lbl == ""):
                    next_id = e.get("target")
                    if lbl.lower() == target_label.lower():
                        break
            if not next_id and next_edges:
                # fallback: pega edge com label correto ou a segunda se fora
                idx = 0 if in_hours else min(1, len(next_edges)-1)
                next_id = next_edges[idx].get("target")
        elif node_type in ("condition.if",):
            result_cond = context["variables"].get("_last_condition", True)
            for e in next_edges:
                lbl = (e.get("label") or "").strip().lower()
                if (result_cond and lbl in ("sim", "yes", "true", "")) or \
                   (not result_cond and lbl in ("não", "no", "false")):
                    next_id = e.get("target"); break
            if not next_id and next_edges:
                next_id = next_edges[0].get("target")
        else:
            next_id = next_edges[0].get("target") if next_edges else None

        current_node = next((n for n in nodes if n["id"] == next_id), None) if next_id else None

    total_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    warnings = [s for s in steps if s["status"] == "warning"]
    errors = [s for s in steps if s["status"] == "error"]

    return {
        "steps": steps,
        "session_history": context.get("_sim_history", []),  # frontend usa para próxima mensagem
        "total_nodes": len(steps),
        "duration_ms": total_ms,
        "warnings": len(warnings),
        "errors": len(errors),
        "final_tags": context["contact"].get("tags", []),
        "final_variables": context.get("variables", {}),
        "summary": (
            f"❌ {len(errors)} erro(s) encontrado(s)" if errors
            else f"⚠️ {len(warnings)} aviso(s) — verifique as configurações" if warnings
            else f"✅ Simulação completa — {len(steps)} nós executados com sucesso"
        )
    }




@router.get("/{flow_id}/executions")
async def get_flow_executions(flow_id: str, workspace_id: str, limit: int = 20):
    supabase = get_supabase()
    result = supabase.table("flow_executions").select("*").eq(
        "flow_id", flow_id
    ).eq("workspace_id", workspace_id).order(
        "started_at", desc=True
    ).limit(limit).execute()
    return result.data


# ══════════════════════════════════════════════
# MOTOR DE EXECUÇÃO DOS FLOWS
# ══════════════════════════════════════════════

async def run_flow(
    flow_id: str,
    workspace_id: str,
    trigger_data: Dict[str, Any],
):
    """Executa um flow node por node"""
    supabase = get_supabase()
    start_time = datetime.now()
    
    # Registrar execução
    exec_result = supabase.table("flow_executions").insert({
        "workspace_id": workspace_id,
        "flow_id": flow_id,
        "status": "running",
        "trigger_data": trigger_data,
    }).execute()
    exec_id = exec_result.data[0]["id"] if exec_result.data else None
    
    try:
        # Buscar flow
        flow = supabase.table("flows").select("*").eq("id", flow_id).limit(1).execute()
        if not flow.data:
            return
        
        nodes = (flow.data[0] if flow.data else {}).get("nodes", [])
        edges = (flow.data[0] if flow.data else {}).get("edges", [])
        
        # Contexto de execução
        context = {
            "workspace_id": workspace_id,
            "trigger_data": trigger_data,
            "contact": trigger_data.get("contact", {}),
            "variables": {},
        }
        
        # Encontrar nó inicial (trigger) — checa tanto type quanto data.nodeType
        start_nodes = [n for n in nodes if 
            n.get("type", "").startswith("trigger.") or 
            n.get("data", {}).get("nodeType", "").startswith("trigger.")
        ]
        print(f"🔍 run_flow: {len(nodes)} nós, {len(edges)} edges, {len(start_nodes)} triggers")
        if not start_nodes:
            print(f"❌ Nenhum trigger encontrado! tipos: {[n.get('type') or n.get('data',{}).get('nodeType') for n in nodes[:5]]}")
            raise ValueError("No trigger node found")
        
        # Executar nodes em sequência
        current_node = start_nodes[0]
        visited = set()
        node_logs = []  # log por nó estilo n8n
        
        while current_node:
            node_id = current_node.get("id")
            if node_id in visited:
                break
            visited.add(node_id)
            
            node_start = datetime.now()
            node_type = current_node.get("data", {}).get("nodeType") or current_node.get("type", "")
            node_label = current_node.get("data", {}).get("label", node_type)
            node_log = {
                "node_id": node_id,
                "node_type": node_type,
                "node_label": node_label,
                "status": "running",
                "input": {k: v for k, v in context.get("variables", {}).items()},
                "output": None,
                "error": None,
                "duration_ms": 0,
                "started_at": node_start.isoformat(),
            }
            
            try:
                result = await execute_node(current_node, context, workspace_id)
                context["variables"][f"node_{node_id}"] = result
                node_log["status"] = "success"
                node_log["output"] = result
            except Exception as node_err:
                node_log["status"] = "error"
                node_log["error"] = str(node_err)
                node_log["output"] = {}
                result = {}
            
            node_log["duration_ms"] = int((datetime.now() - node_start).total_seconds() * 1000)
            node_logs.append(node_log)
            
            # Atualiza exec com logs parciais em tempo real
            if exec_id:
                supabase.table("flow_executions").update({
                    "node_logs": node_logs,
                }).eq("id", exec_id).execute()
            
            # Para se erro no nó
            if node_log["status"] == "error":
                raise Exception(f"Erro no nó '{node_label}': {node_log['error']}")
            
            # Se flow está aguardando input do usuário — para aqui
            if context.get("_waiting_input"):
                break
            
            # Se for condição, decide próximo node
            node_type_check = current_node.get("type", "") or current_node.get("data", {}).get("nodeType", "")
            print(f"🔗 nó {node_label!r} type={node_type_check!r} result={str(result)[:100]}")
            # Para o flow se o nó pediu (ex: inactivity, delay longo)
            if isinstance(result, dict) and result.get("_stop_flow"):
                print(f"⏹️ Flow pausado por {node_type_check}")
                break
            if node_type_check.startswith("condition."):
                next_id = result.get("next_node_id")
                if not next_id and "result" in result:
                    r = result["result"]
                    all_edges = [e for e in edges if e.get("source") == node_id]
                    print(f"🔗 condition edges raw: {[(e.get('target'), e.get('sourceHandle'), e.get('label')) for e in all_edges]}")

                    # 1. sourceHandle explícito
                    true_edges  = [e for e in all_edges if str(e.get("sourceHandle","")).lower() in ("true","yes","1","a")]
                    false_edges = [e for e in all_edges if str(e.get("sourceHandle","")).lower() in ("false","no","0","b")]

                    # 2. label da edge
                    if not true_edges and not false_edges:
                        true_edges  = [e for e in all_edges if str(e.get("label","")).lower() in ("sim","yes","true","dentro","✓","dentro do horário","horário comercial")]
                        false_edges = [e for e in all_edges if str(e.get("label","")).lower() in ("não","nao","no","false","fora","✗","fora do horário","fora do horario")]

                    # 3. label do nó destino
                    if not true_edges and not false_edges and len(all_edges) >= 2:
                        negative_words = ["fora","out","ausên","ausenc","fechad","indispon","negat","não atend","sem atend"]
                        positive_words = ["ia","responde","atend","dentro","comercial","ativo","ai"]
                        def score(target_id, words):
                            n = next((x for x in nodes if x.get("id") == target_id), {})
                            lbl = n.get("data", {}).get("label", "").lower()
                            return sum(1 for w in words if w in lbl)
                        # Ordena: maior score positive = true, maior score negative = false
                        sorted_by_positive = sorted(all_edges, key=lambda e: score(e.get("target",""), positive_words), reverse=True)
                        sorted_by_negative = sorted(all_edges, key=lambda e: score(e.get("target",""), negative_words), reverse=True)
                        if score(sorted_by_negative[0].get("target",""), negative_words) > 0:
                            false_edges = [sorted_by_negative[0]]
                            true_edges  = [e for e in all_edges if e != false_edges[0]]
                        else:
                            true_edges  = [sorted_by_positive[0]]
                            false_edges = [e for e in all_edges if e != true_edges[0]]

                    chosen = true_edges if r else false_edges
                    next_id = chosen[0].get("target") if chosen else None
                    print(f"🔗 condition result={r} true_targets={[e.get('target') for e in true_edges]} false_targets={[e.get('target') for e in false_edges]} → next={next_id}")
            else:
                next_edges = [e for e in edges if e.get("source") == node_id]
                next_id = next_edges[0].get("target") if next_edges else None
            print(f"🔗 próximo nó: {next_id!r}")
            
            if next_id:
                current_node = next((n for n in nodes if n["id"] == next_id), None)
            else:
                break
        
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        
        if exec_id:
            supabase.table("flow_executions").update({
                "status": "success",
                "result": context["variables"],
                "node_logs": node_logs,
                "duration_ms": duration,
                "finished_at": datetime.now().isoformat(),
            }).eq("id", exec_id).execute()
        
        supabase.table("flows").update({
            "last_run_at": datetime.now().isoformat(),
            "run_count": supabase.rpc("increment", {"x": 1}).execute(),
        }).eq("id", flow_id).execute()
        
    except Exception as e:
        duration = int((datetime.now() - start_time).total_seconds() * 1000)
        if exec_id:
            supabase.table("flow_executions").update({
                "status": "failed",
                "error": str(e),
                "node_logs": node_logs if 'node_logs' in locals() else [],
                "duration_ms": duration,
                "finished_at": datetime.now().isoformat(),
            }).eq("id", exec_id).execute()


async def execute_node(node: Dict, context: Dict, workspace_id: str) -> Dict:
    """Executa um nó individual — suporte a todos os 45 tipos"""
    node_type = node.get("data", {}).get("nodeType") or node.get("type", "")
    config    = interpolate_variables(node.get("data", {}).get("config", {}), context)
    supabase  = get_supabase()
    print(f"🔧 execute_node: type={node_type} contact={context.get('contact',{}).get('phone','?')} simulating={context.get('_simulating')}")

    # ── TRIGGERS ──────────────────────────────────────────────────────────────
    if node_type.startswith("trigger."):
        return {"status": "trigger", "data": context.get("trigger_data", {})}

    # ── LÓGICA ────────────────────────────────────────────────────────────────
    elif node_type == "condition.delay":
        unit = config.get("unit", "seconds")
        dur  = float(config.get("duration", 1))
        secs = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}.get(unit, 1)
        total_secs = dur * secs
        if not context.get("_simulating"):
            if total_secs <= 30:
                # Delay curto — executa inline
                await asyncio.sleep(total_secs)
            else:
                # Delay longo — agenda no scheduler para retomar o flow
                from datetime import timezone as _tz
                resume_at = (datetime.now(_tz.utc) + __import__("datetime").timedelta(seconds=total_secs)).isoformat()
                supabase.table("flow_resumptions").insert({
                    "workspace_id": workspace_id,
                    "flow_id": flow_id,
                    "contact_phone": context.get("contact", {}).get("phone", ""),
                    "resume_after_node": node.get("id"),
                    "resume_at": resume_at,
                    "context_snapshot": {
                        "variables": context.get("variables", {}),
                        "contact": context.get("contact", {}),
                    },
                }).execute()
                print(f"⏰ Delay longo: flow pausado, retoma em {resume_at}")
                return {"status": "delayed_scheduled", "resume_at": resume_at, "_stop_flow": True}
        return {"status": "delayed", "duration": f"{dur} {unit}"}

    elif node_type == "condition.if":
        # Suporta tanto "field" quanto "var_name" para buscar a variável
        field = config.get("field", "") or config.get("var_name", "")
        fv = context.get("variables", {}).get(field, "") or get_nested_value(context, field)
        result = evaluate_condition(fv, config.get("operator", "equals"), config.get("value", ""))
        print(f"🔀 condition.if: field={field!r} valor={fv!r} operator={config.get('operator')} expected={config.get('value')!r} result={result}")
        context["variables"]["_last_condition"] = result
        return {"status": "condition", "result": result,
                "next_node_id": node.get("data", {}).get("true_node" if result else "false_node")}

    elif node_type == "condition.switch":
        field = config.get("field", "")
        fv    = str(get_nested_value(context, field) or "")
        for i in range(1, 4):
            cv = str(config.get(f"case{i}_value", "")).strip()
            if cv and (fv == cv or fv.lower() == cv.lower()):
                return {"status": "switch", "matched_case": i, "value": fv}
        return {"status": "switch", "matched_case": "default", "value": fv}

    elif node_type == "condition.time_check":
        from datetime import timezone as _tz, timedelta as _td
        # Mapa de fusos brasileiros — sem pytz, usando offset fixo
        TZ_OFFSETS = {
            "America/Fortaleza":   -3, "America/Recife":      -3,
            "America/Sao_Paulo":   -3, "America/Belem":       -3,
            "America/Manaus":      -4, "America/Porto_Velho": -4,
            "America/Boa_Vista":   -4, "America/Rio_Branco":  -5,
            "America/Noronha":     -2,
        }
        tz_name = config.get("timezone") or "America/Fortaleza"
        offset = TZ_OFFSETS.get(tz_name, -3)  # default UTC-3 Brasil
        br_tz = _tz(_td(hours=offset))
        now = datetime.now(_tz.utc).astimezone(br_tz)

        start_h, start_m = [int(x) for x in (config.get("start_time", "08:00") + ":00").split(":")[:2]]
        end_h,   end_m   = [int(x) for x in (config.get("end_time",   "18:00") + ":00").split(":")[:2]]
        start_mins = start_h * 60 + start_m
        end_mins   = end_h   * 60 + end_m
        cur_mins   = now.hour * 60 + now.minute
        days_cfg   = config.get("days", "mon,tue,wed,thu,fri").split(",")
        day_map    = {"mon":0,"tue":1,"wed":2,"thu":3,"fri":4,"sat":5,"sun":6}
        in_hours   = start_mins <= cur_mins <= end_mins
        in_days    = any(day_map.get(d.strip()) == now.weekday() for d in days_cfg)
        result     = in_hours and in_days
        context["variables"]["_in_business_hours"] = result
        return {
            "status": "time_check",
            "result": result,
            "current_time": now.strftime("%H:%M"),
            "timezone": tz_name,
            "debug": f"{now.strftime('%A %H:%M')} UTC{offset:+d} | horario={in_hours} dias={in_days} => {'DENTRO' if result else 'FORA'}"
        }

    elif node_type == "condition.inactivity":
        # Agenda reativação da IA salvando nos metadados da conversa
        unit = config.get("unit", "minutes")
        dur  = float(config.get("duration", 30))
        secs = {"seconds": 1, "minutes": 60, "hours": 3600}.get(unit, 60)
        total_secs = dur * secs
        from datetime import timezone as _tz
        resume_at = (datetime.now(_tz.utc) + __import__("datetime").timedelta(seconds=total_secs)).isoformat()
        reactivate_msg = config.get("message", "Olá! Vou continuar seu atendimento. Como posso ajudar?")
        contact_id = context.get("contact", {}).get("id", "")
        if contact_id:
            try:
                import json
                supabase.table("conversations").update({
                    "metadata": json.dumps({
                        "reactivate_at": resume_at,
                        "reactivate_message": reactivate_msg,
                    })
                }).eq("workspace_id", workspace_id).eq("contact_id", contact_id).execute()
                print(f"⏰ Inatividade: reativa em {resume_at} para contact_id={contact_id}")
            except Exception as _re:
                print(f"❌ inactivity save error: {_re}")
        return {"status": "inactivity_scheduled", "resume_at": resume_at, "_stop_flow": True}

    elif node_type == "condition.loop":
        counter_key = f"_loop_{node.get('id','')}"
        count = context["variables"].get(counter_key, 0) + 1
        context["variables"][counter_key] = count
        max_iter = int(config.get("max_iterations", 3))
        return {"status": "loop", "iteration": count, "continue": count < max_iter}

    elif node_type == "condition.ab_test":
        import random
        pct_a  = int(config.get("percent_a", 50))
        branch = "a" if random.randint(1, 100) <= pct_a else "b"
        context["variables"]["_ab_branch"] = branch
        return {"status": "ab_test", "branch": branch}

    elif node_type == "condition.counter":
        name  = config.get("counter_name", "counter")
        limit = int(config.get("limit", 99))
        count = context["variables"].get(f"_cnt_{name}", 0) + 1
        context["variables"][f"_cnt_{name}"] = count
        return {"status": "counter", "count": count, "limit_reached": count >= limit}

    elif node_type == "condition.set_variable":
        name  = config.get("var_name", "")
        value = config.get("var_value", "")
        if name:
            context["variables"][name] = value
        return {"status": "variable_set", "name": name, "value": value}

    elif node_type == "condition.subflow":
        subflow_id = config.get("subflow_id", "")
        if subflow_id and not context.get("_simulating"):
            sub = supabase.table("flows").select("*").eq("id", subflow_id).limit(1).execute()
            if sub.data:
                sub_context = {**context, "variables": dict(context.get("variables", {}))}
                for sub_node_data in ((sub.data[0] if sub.data else {}).get("nodes") or []):
                    await execute_node(sub_node_data, sub_context, workspace_id)
        return {"status": "subflow_called", "subflow_id": subflow_id}

    # ── WHATSAPP ──────────────────────────────────────────────────────────────
    elif node_type == "action.send_text":
        # Resolve {{workspace.notification_phone}}
        _to_raw = config.get("to", "") or ""
        if "{{workspace.notification_phone}}" in _to_raw or "{{workspace." in _to_raw:
            from app.core.database import get_supabase as _gsb
            _wsinfo = _gsb().table("workspaces").select("notification_phone, name").eq(
                "id", workspace_id).limit(1).execute()
            _wsd = _wsinfo.data[0] if _wsinfo.data else {}
            _to_raw = _to_raw.replace("{{workspace.notification_phone}}", _wsd.get("notification_phone", ""))
            _to_raw = _to_raw.replace("{{workspace.name}}", _wsd.get("name", ""))
        phone   = _to_raw or context.get("contact", {}).get("phone", "")
        contact = context.get("contact", {})
        # Resolve variáveis de contato na mensagem
        message = config.get("message", "")
        message = message.replace("{{contact.name}}", contact.get("name", contact.get("phone", "")))
        message = message.replace("{{contact.phone}}", contact.get("phone", ""))
        # Busca notes do contato
        try:
            from app.core.database import get_supabase as _gsb2
            _ct = _gsb2().table("contacts").select("notes").eq(
                "workspace_id", workspace_id).eq("phone", contact.get("phone","")).limit(1).execute()
            _notes = (_ct.data[0] if _ct.data else {}).get("notes", "") or ""
        except Exception:
            _notes = ""
        message = message.replace("{{contact.notes}}", _notes)
        print(f"📤 action.send_text: phone={phone!r} message={message[:80]!r} simulating={context.get('_simulating')}")
        if phone and message and not context.get("_simulating"):
            result = await whatsapp_client.send_text(phone, message, workspace_id)
            print(f"📤 send_text result: {result}")
            # Salva mensagem enviada no histórico
            try:
                from app.services.message_service import save_message, get_conversation
                contact_id = context.get("contact", {}).get("id")
                if contact_id:
                    conv = await get_conversation(workspace_id, contact_id)
                    await save_message(workspace_id, conv.get("id"), {
                        "contact_id": contact_id,
                        "direction": "outbound",
                        "content": message,
                        "type": "text",
                        "is_ai": True,
                    })
            except Exception as e:
                print(f"⚠️ save_message error: {e}")
        elif not phone:
            print(f"❌ send_text: phone vazio! contact={context.get('contact')}")
        elif not message:
            print(f"❌ send_text: message vazio! config={config}")
        return {"status": "sent", "to": phone, "message": message[:200]}

    elif node_type == "action.send_whatsapp_notification":
        # Envia notificação para o número configurado no workspace (notification_phone)
        from app.core.database import get_supabase as _get_sb
        _sb = _get_sb()
        _ws = _sb.table("workspaces").select("notification_phone, name").eq(
            "id", workspace_id).limit(1).execute()
        _ws_data = _ws.data[0] if _ws.data else {}
        notif_phone = _ws_data.get("notification_phone", "")
        ws_name = _ws_data.get("name", "Sistema")
        contact = context.get("contact", {})
        # Busca notes do contato no banco (não vem no context padrão)
        contact_notes = contact.get("notes", "")
        try:
            ct = _sb.table("contacts").select("notes").eq(
                "workspace_id", workspace_id).eq("phone", contact.get("phone","")).limit(1).execute()
            if ct.data:
                contact_notes = ct.data[0].get("notes", "") or ""
        except Exception:
            pass

        if notif_phone and not context.get("_simulating"):
            msg_template = config.get("message", "")
            msg_template = msg_template.replace("{{workspace.notification_phone}}", notif_phone)
            msg_template = msg_template.replace("{{workspace.name}}", ws_name)
            msg_template = msg_template.replace("{{contact.name}}", contact.get("name", contact.get("phone", "")))
            msg_template = msg_template.replace("{{contact.phone}}", contact.get("phone", ""))
            msg_template = msg_template.replace("{{contact.notes}}", contact_notes)
            print(f"📣 send_whatsapp_notification → {notif_phone}: {msg_template[:80]!r}")
            await whatsapp_client.send_text(notif_phone, msg_template, workspace_id)
        elif not notif_phone:
            print(f"⚠️ notification_phone não configurado no workspace")
        return {"status": "notification_sent", "to": notif_phone}

    elif node_type == "action.send_image":
        phone = config.get("to", "") or context.get("contact", {}).get("phone", "")
        # Resolve media_file_id para URL pública
        media_url = config.get("media_url", "")
        if not media_url and config.get("media_file_id"):
            mf = supabase.table("media_files").select("public_url").eq(
                "id", config["media_file_id"]).limit(1).execute()
            if mf.data:
                media_url = mf.data[0].get("public_url", "")
        if phone and media_url and not context.get("_simulating"):
            await whatsapp_client.send_image(phone, media_url, config.get("caption",""), workspace_id)
        return {"status": "sent", "type": "image"}

    elif node_type == "action.send_document":
        phone = config.get("to", "") or context.get("contact", {}).get("phone", "")
        if phone and config.get("document_url") and not context.get("_simulating"):
            await whatsapp_client.send_document(phone, config["document_url"], config.get("filename","doc.pdf"), workspace_id)
        return {"status": "sent", "type": "document"}

    elif node_type == "action.send_audio":
        phone = config.get("to", "") or context.get("contact", {}).get("phone", "")
        if phone and config.get("media_url") and not context.get("_simulating"):
            await whatsapp_client.send_audio(phone, config["media_url"], workspace_id)
        return {"status": "sent", "type": "audio"}

    elif node_type == "action.send_buttons":
        phone   = config.get("to", "") or context.get("contact", {}).get("phone", "")
        message = config.get("message", "")
        # Suporta btn1/btn2/btn3 ou lista buttons [{id, text}]
        if config.get("buttons") and isinstance(config["buttons"], list):
            buttons = [b.get("text", b) if isinstance(b, dict) else b for b in config["buttons"] if b]
        else:
            buttons = [b for b in [config.get("btn1"), config.get("btn2"), config.get("btn3")] if b]
        # Substitui variáveis de contato na mensagem
        contact = context.get("contact", {})
        message = message.replace("{{contact.name}}", contact.get("name", contact.get("phone", "")))
        if phone and message and buttons and not context.get("_simulating"):
            await whatsapp_client.send_buttons(phone, message, buttons, workspace_id)
        return {"status": "sent", "type": "buttons", "buttons": buttons}

    elif node_type == "action.send_list":
        phone    = config.get("to", "") or context.get("contact", {}).get("phone", "")
        message  = config.get("message", "")
        title    = config.get("list_title", "Opções")
        raw_items = config.get("items", "")
        items    = [i.strip() for i in str(raw_items).split("\n") if i.strip()]
        if phone and message and items and not context.get("_simulating"):
            await whatsapp_client.send_list(phone, message, title, items, workspace_id)
        return {"status": "sent", "type": "list", "items": items}

    elif node_type == "action.send_location":
        phone = config.get("to", "") or context.get("contact", {}).get("phone", "")
        if phone and config.get("latitude") and not context.get("_simulating"):
            await whatsapp_client.send_location(
                phone, float(config["latitude"]), float(config["longitude"]),
                config.get("name",""), config.get("address",""), workspace_id
            )
        return {"status": "sent", "type": "location", "lat": config.get("latitude"), "lng": config.get("longitude")}

    elif node_type == "action.wait_reply":
        timeout_min = int(config.get("timeout_minutes", 60))
        context["variables"]["_waiting_reply"] = True
        context["variables"]["_reply_timeout_min"] = timeout_min
        return {"status": "waiting_reply", "timeout_minutes": timeout_min}

    elif node_type == "action.collect_data":
        question  = config.get("question", "")
        var_name  = config.get("variable", "resposta")
        phone     = context.get("contact", {}).get("phone", "")
        if question and phone and not context.get("_simulating"):
            await whatsapp_client.send_text(phone, question, workspace_id)
        # Salvar a resposta que vier como trigger_data
        incoming = context.get("trigger_data", {}).get("message", "") or context.get("message", {}).get("content", "")
        if var_name and incoming:
            context["variables"][var_name] = incoming
        return {"status": "data_collected", "variable": var_name, "value": incoming}

    elif node_type == "action.check_read":
        return {"status": "read_check_scheduled", "wait_hours": config.get("wait_hours", 2)}

    # ── IA ───────────────────────────────────────────────────────────────────
    elif node_type == "action.ai_respond":
        from app.services.ai_service import generate_ai_response
        contact = context.get("contact", {})
        print(f"🤖 ai_respond START: contact={contact} phone={contact.get('phone')} id={contact.get('id')}")
        # Verifica se IA está pausada
        _contact_id = contact.get("id", "")
        if _contact_id:
            _conv = supabase.table("conversations").select("ai_status").eq(
                "workspace_id", workspace_id).eq("contact_id", _contact_id).limit(1).execute()
            _ai_status = (_conv.data[0] if _conv.data else {}).get("ai_status", "active")
            if _ai_status == "paused":
                print(f"⏸️ IA pausada — pulando ai_respond")
                return {"status": "ai_paused_skip"}
        # Pega conteúdo: raw_media_dict para mídia, texto simples para texto
        raw_media = context.get("trigger_data", {}).get("raw_media_dict")
        _td_msg = context.get("trigger_data", {}).get("message", "")
        # trigger_data["message"] pode ser string ou dict {"content": ..., "type": ...}
        if isinstance(_td_msg, dict):
            _td_msg = _td_msg.get("content", "")
        raw_msg = raw_media if (raw_media and isinstance(raw_media, dict) and raw_media.get("URL")) else _td_msg
        print(f"🔑 raw_msg={str(raw_msg)[:80]!r}")
        phone   = contact.get("phone", "")

        # Se o conteúdo é dict de mídia válido (tem URL ou mediaKey)
        if isinstance(raw_msg, dict) and (raw_msg.get("URL") or raw_msg.get("url") or raw_msg.get("mediaKey")):
            try:
                from app.services.whatsapp_media import media_handler as _mh
                # Detecta tipo pela mimetype do próprio dict
                mimetype = raw_msg.get("mimetype", "")
                if "image" in mimetype or "jpeg" in mimetype or "png" in mimetype:
                    msg_type = "image"
                elif "audio" in mimetype or "ogg" in mimetype or "mp4" in mimetype:
                    msg_type = "audio"
                elif "pdf" in mimetype or "document" in mimetype:
                    msg_type = "document"
                else:
                    # fallback pelo wa_lastMessageType do chat
                    wa_type = context.get("trigger_data", {}).get("wa_lastMessageType", "") or ""
                    if "Image" in wa_type:
                        msg_type = "image"
                    elif "Audio" in wa_type or "Ptt" in wa_type:
                        msg_type = "audio"
                    else:
                        msg_type = "image"
                caption = raw_msg.get("caption", "")
                print(f"🤖 processando mídia tipo={msg_type} mimetype={mimetype}")
                message = await _mh.process_media(msg_type, raw_msg, caption)
                print(f"🤖 mídia processada: {message[:100]!r}")
            except Exception as me:
                import traceback; traceback.print_exc()
                print(f"⚠️ whatsapp_media error: {me}")
                message = "[Cliente enviou uma mídia]"
        else:
            message = str(raw_msg) if raw_msg else ""

        print(f"🤖 ai_respond: phone={phone!r} message={message[:100]!r} simulating={context.get('_simulating')}")
        if phone and message and not context.get("_simulating"):
            try:
                conv_id = None
                contact_id = contact.get("id")
                if contact_id:
                    from app.services.message_service import get_conversation
                    conv = await get_conversation(workspace_id, contact_id)
                    conv_id = conv.get("id")
                response_text = await generate_ai_response(message, contact, workspace_id, config.get("context_override"))
                print(f"🤖 ai_respond gerou: {response_text[:200]!r}")
                if response_text:
                    result = await whatsapp_client.send_text(phone, response_text, workspace_id)
                    print(f"🤖 send_text result: {result}")
                else:
                    print(f"❌ ai_respond: resposta vazia!")
            except Exception as ai_err:
                import traceback; traceback.print_exc()
                print(f"❌ ai_respond erro: {ai_err}")
            # Salva mensagem da IA no histórico
            try:
                from app.services.message_service import save_message
                if conv_id and contact_id:
                    await save_message(workspace_id, conv_id, {
                        "contact_id": contact_id,
                        "direction": "outbound",
                        "content": response_text,
                        "type": "text",
                        "is_ai": True,
                    })
            except Exception as e:
                print(f"⚠️ save_message error: {e}")
            return {"status": "ai_responded", "response": response_text[:300]}
        if not phone:
            print(f"❌ ai_respond: phone vazio! contact={contact}")
        if not message:
            print(f"❌ ai_respond: message vazio!")
        return {"status": "ai_respond_simulated"}

    elif node_type == "action.ai_classify":
        from app.services.ai_service import classify_message
        message = context.get("message", {}).get("content", "") or context.get("trigger_data", {}).get("message", "")
        cats    = config.get("categories", "").split(",")
        field   = config.get("output_field", "classification")
        if message and not context.get("_simulating"):
            result = await classify_message(message, cats, workspace_id)
            context["variables"][field] = result
            return {"status": "classified", "result": result}
        return {"status": "classify_simulated"}

    elif node_type == "action.ai_extract":
        from app.services.ai_service import extract_entities
        message      = context.get("message", {}).get("content", "") or context.get("trigger_data", {}).get("message", "")
        extract_what = config.get("extract_fields", "nome, data, telefone")
        field        = config.get("output_field", "dados_extraidos")
        if message and not context.get("_simulating"):
            extracted = await extract_entities(message, extract_what, workspace_id)
            context["variables"][field] = extracted
            return {"status": "extracted", "result": extracted}
        return {"status": "extract_simulated"}

    elif node_type == "action.ai_summarize":
        from app.services.ai_service import summarize_conversation
        contact = context.get("contact", {})
        field   = config.get("output_field", "resumo_conversa")
        if contact.get("phone") and not context.get("_simulating"):
            summary = await summarize_conversation(contact["phone"], workspace_id, int(config.get("max_lines", 5)))
            context["variables"][field] = summary
            return {"status": "summarized", "summary": summary[:500]}
        return {"status": "summarize_simulated"}

    elif node_type == "action.ai_sentiment":
        from app.services.ai_service import analyze_sentiment
        message = context.get("message", {}).get("content", "") or context.get("trigger_data", {}).get("message", "")
        field   = config.get("output_field", "sentimento")
        escalate_on = [s.strip() for s in config.get("escalate_on", "negativo,frustrado").split(",")]
        if message and not context.get("_simulating"):
            sentiment = await analyze_sentiment(message, workspace_id)
            context["variables"][field] = sentiment
            should_escalate = any(e.lower() in sentiment.lower() for e in escalate_on)
            return {"status": "sentiment_analyzed", "sentiment": sentiment, "escalate": should_escalate}
        return {"status": "sentiment_simulated"}

    elif node_type == "action.ai_reactivate":
        phone = context.get("contact", {}).get("phone", "")
        if phone:
            supabase.table("conversations").update({"ai_status": "active"}).eq("workspace_id", workspace_id).eq("contact_id", context.get("contact",{}).get("id","")).execute()
            msg = config.get("message", "")
            if msg and not context.get("_simulating"):
                await whatsapp_client.send_text(phone, msg, workspace_id)
        return {"status": "ai_reactivated"}

    elif node_type == "action.ai_pause":
        phone = context.get("contact", {}).get("phone", "")
        if phone:
            supabase.table("conversations").update({"ai_status": "paused"}).eq("workspace_id", workspace_id).eq("contact_id", context.get("contact",{}).get("id","")).execute()
        return {"status": "ai_paused"}

    # ── AGENDA ────────────────────────────────────────────────────────────────
    elif node_type == "action.create_appointment":
        contact = context.get("contact", {})
        contact_result = supabase.table("contacts").select("id").eq("workspace_id", workspace_id).eq("phone", contact.get("phone","")).limit(1).execute()
        contact_id = (contact_result.data[0] if contact_result.data else {}).get("id") if contact_result.data else None
        apt_id = None
        if contact_id:
            apt_result = supabase.table("appointments").insert({
                "workspace_id": workspace_id,
                "contact_id":   contact_id,
                "title":        config.get("title", "Consulta"),
                "status":       "scheduled",
                "professional": config.get("professional", ""),
                "start_time":   context["variables"].get("appointment_time", datetime.now().isoformat()),
                "duration_minutes": int(config.get("duration_minutes", 60)),
                "reminder_sent": False,
            }).execute()
            apt_id = (apt_result.data[0] if apt_result.data else {}).get("id")
            
            # Dispara flow de lembrete (trigger.appointment_created)
            if apt_id and not context.get("_simulating"):
                try:
                    reminder_flows = supabase.table("flows").select("id").eq(
                        "workspace_id", workspace_id).eq("is_active", True).execute()
                    for rf in (reminder_flows.data or []):
                        rf_data = supabase.table("flows").select("nodes").eq(
                            "id", rf["id"]).limit(1).execute()
                        if rf_data.data:
                            nodes_check = rf_data.data[0].get("nodes", [])
                            if any(n.get("data",{}).get("nodeType") == "trigger.appointment_created" for n in nodes_check):
                                apt_context = {
                                    "contact": context.get("contact", {}),
                                    "trigger_data": {"appointment_id": apt_id, "phone": context.get("contact",{}).get("phone","")},
                                    "variables": {"appointment_id": apt_id, **context.get("variables", {})},
                                    "_simulating": False,
                                }
                                import asyncio as _asyncio
                                _asyncio.create_task(run_flow(rf["id"], workspace_id, apt_context))
                                print(f"📅 Flow de lembrete disparado para agendamento {apt_id}")
                                break
                except Exception as _e:
                    print(f"⚠️ Erro ao disparar flow de lembrete: {_e}")

        return {"status": "appointment_created", "appointment_id": apt_id}

    elif node_type == "action.cancel_appointment":
        contact = context.get("contact", {})
        supabase.table("appointments").update({"status": "cancelled", "notes": config.get("reason","")}).eq("workspace_id", workspace_id).eq("contact_phone", contact.get("phone","")).eq("status", "scheduled").execute()
        return {"status": "appointment_cancelled"}

    elif node_type == "action.check_availability":
        prof   = config.get("professional", "")
        q      = supabase.table("appointments").select("id").eq("workspace_id", workspace_id).eq("status", "scheduled")
        if prof:
            q = q.eq("professional", prof)
        result = q.execute()
        has_slots = len(result.data or []) < 10
        context["variables"][config.get("output_field", "disponibilidade")] = "disponivel" if has_slots else "indisponivel"
        return {"status": "availability_checked", "available": has_slots}

    elif node_type == "action.send_reminder":
        phone       = context.get("contact", {}).get("phone", "")
        message     = config.get("message", "Lembrete da sua consulta!")
        use_buttons = config.get("use_buttons", False)
        if phone and not context.get("_simulating"):
            if use_buttons:
                await whatsapp_client.send_buttons(
                    phone, message,
                    [{"id": "confirm_yes", "text": "Confirmo!"},
                     {"id": "confirm_no",  "text": "Preciso remarcar"}],
                    workspace_id
                )
            else:
                await whatsapp_client.send_text(phone, message, workspace_id)
        return {"status": "reminder_sent", "buttons": use_buttons}

    elif node_type == "action.confirm_appointment":
        phone      = context.get("contact", {}).get("phone", "")
        contact_id = context.get("contact", {}).get("id", "")
        apt_id     = config.get("appointment_id") or context.get("variables", {}).get("appointment_id", "")
        msg_text   = config.get("message", "")
        from datetime import timezone as _tz, timedelta as _tdd
        if not apt_id and contact_id:
            now_utc = datetime.now(_tz.utc)
            future  = (now_utc + _tdd(hours=26)).isoformat()
            apt_r = supabase.table("appointments").select("*").eq(
                "workspace_id", workspace_id
            ).eq("contact_id", contact_id).eq("status", "scheduled").gte(
                "start_time", now_utc.isoformat()
            ).lte("start_time", future).order("start_time").limit(1).execute()
            if apt_r.data:
                apt      = apt_r.data[0]
                apt_id   = apt["id"]
                apt_dt   = datetime.fromisoformat(apt["start_time"][:16])
                dt_str   = apt_dt.strftime("%d/%m/%Y as %H:%M")
                title    = apt.get("title", "Consulta")
                prof     = apt.get("professional", "")
                prof_ln  = ("Prof.: " + prof + " ") if prof else ""
                msg_text = "Ola! Lembrete: " + title + " em " + dt_str + ". " + prof_ln + "Confirma?"
        if not msg_text:
            msg_text = "Voce confirma sua consulta?"
        if phone and not context.get("_simulating"):
            await whatsapp_client.send_buttons(
                phone, msg_text,
                [{"id": "apt_yes_" + str(apt_id), "text": "Confirmo!"},
                 {"id": "apt_no_"  + str(apt_id), "text": "Remarcar"}],
                workspace_id
            )
            if contact_id:
                supabase.table("conversations").update({
                    "ai_status":           "waiting_confirmation",
                    "waiting_appointment": str(apt_id),
                }).eq("workspace_id", workspace_id).eq("contact_id", contact_id).execute()
        return {"status": "confirmation_sent", "appointment_id": str(apt_id)}

    # ── CONTATOS ──────────────────────────────────────────────────────────────
    elif node_type == "action.add_tag":
        tag   = config.get("tag", "").strip().lower()
        phone = context.get("contact", {}).get("phone", "")
        if tag and phone:
            row = supabase.table("contacts").select("tags").eq("workspace_id", workspace_id).eq("phone", phone).limit(1).execute()
            current = (row.data[0] if row.data else {}).get("tags") or [] if row.data else []
            if tag not in current:
                supabase.table("contacts").update({"tags": current + [tag]}).eq("workspace_id", workspace_id).eq("phone", phone).execute()
            context.get("contact", {}).setdefault("tags", [])
            if tag not in context["contact"].get("tags", []):
                context["contact"].setdefault("tags", []).append(tag)
        return {"status": "tag_added", "tag": tag}

    elif node_type == "action.remove_tag":
        tag   = config.get("tag", "").strip().lower()
        phone = context.get("contact", {}).get("phone", "")
        if tag and phone:
            row = supabase.table("contacts").select("tags").eq("workspace_id", workspace_id).eq("phone", phone).limit(1).execute()
            current = (row.data[0] if row.data else {}).get("tags") or [] if row.data else []
            supabase.table("contacts").update({"tags": [t for t in current if t != tag]}).eq("workspace_id", workspace_id).eq("phone", phone).execute()
        return {"status": "tag_removed", "tag": tag}

    elif node_type == "action.create_contact":
        phone = context.get("contact", {}).get("phone", "") or context.get("trigger_data", {}).get("phone", "")
        if phone:
            existing = supabase.table("contacts").select("id").eq("workspace_id", workspace_id).eq("phone", phone).execute()
            if not existing.data:
                tags = [t.strip() for t in config.get("tags", "novo").split(",") if t.strip()]
                supabase.table("contacts").insert({"workspace_id": workspace_id, "phone": phone, "name": config.get("name", ""), "tags": tags}).execute()
        return {"status": "contact_created_or_existing"}

    elif node_type == "action.update_contact":
        phone = context.get("contact", {}).get("phone", "")
        field = config.get("field", "notes")
        value = config.get("value", "")
        if phone and field:
            supabase.table("contacts").update({field: value}).eq("workspace_id", workspace_id).eq("phone", phone).execute()
        return {"status": "contact_updated", "field": field}

    elif node_type == "action.score_contact":
        phone = context.get("contact", {}).get("phone", "")
        pts   = int(config.get("points", 0))
        field = config.get("score_field", "lead_score")
        if phone:
            row = supabase.table("contacts").select(field).eq("workspace_id", workspace_id).eq("phone", phone).limit(1).execute()
            current_score = int((row.data[0] if row.data else {}).get(field) or 0) if row.data else 0
            new_score = max(0, current_score + pts)
            supabase.table("contacts").update({field: new_score}).eq("workspace_id", workspace_id).eq("phone", phone).execute()
            context["variables"][f"_score_{field}"] = new_score
        return {"status": "contact_scored", "points": pts}

    elif node_type == "action.block_contact":
        phone = context.get("contact", {}).get("phone", "")
        if phone:
            supabase.table("contacts").update({"notes": f"[BLOQUEADO] {config.get('reason','')}", "tags": ["bloqueado"]}).eq("workspace_id", workspace_id).eq("phone", phone).execute()
        return {"status": "contact_blocked"}

    elif node_type == "action.notify_team":
        phone   = config.get("phone", "")
        message = config.get("message", "")
        if phone and message and not context.get("_simulating"):
            await whatsapp_client.send_text(phone, message, workspace_id)
        return {"status": "team_notified", "to": phone}

    # ── INTEGRAÇÕES ───────────────────────────────────────────────────────────
    elif node_type == "action.http_request":
        url    = config.get("url", "")
        method = config.get("method", "GET")
        if not url:
            return {"status": "error", "error": "URL não configurada"}
        async with httpx.AsyncClient(timeout=30) as client:
            hdrs = {}
            try:
                hdrs = json.loads(config.get("headers") or "{}")
            except Exception:
                pass
            body = None
            try:
                body = json.loads(config.get("body") or "{}")
            except Exception:
                pass
            resp = await client.request(method, url, headers=hdrs, json=body)
            result_text = resp.text[:2000]
            out_field = config.get("output_field", "http_response")
            context["variables"][out_field] = result_text
            return {"status": "ok", "status_code": resp.status_code, "response": result_text}

    elif node_type == "action.send_email":
        return await _send_email_node(config, context)

    elif node_type == "action.webhook_send":
        url = config.get("url", "")
        if not url:
            return {"status": "error", "error": "URL não configurada"}
        payload = {}
        try:
            payload = json.loads(config.get("payload") or "{}")
        except Exception:
            payload = {"event": "flow_action", "contact": context.get("contact", {})}
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(url, json=payload)
        return {"status": "webhook_sent", "url": url}

    return {"status": "unknown_node", "type": node_type}


async def _send_email_node(config: dict, context: dict) -> dict:
    """Envia email via SMTP configurado no .env"""
    import os, smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")

    if not smtp_host:
        return {"status": "skipped", "reason": "SMTP não configurado no .env (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS)"}

    to_addr  = config.get("to", "")
    subject  = config.get("subject", "Mensagem Nutty.AI")
    body     = config.get("body", "")

    if not to_addr or not body:
        return {"status": "error", "error": "Email: destinatário ou corpo vazio"}

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_user
        msg["To"]      = to_addr
        msg.attach(MIMEText(body, "plain", "utf-8"))
        html_body = body.replace("\n", "<br>")
        msg.attach(MIMEText(f"<html><body><p>{html_body}</p></body></html>", "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.ehlo()
            if smtp_port in (587, 465):
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_addr, msg.as_string())

        return {"status": "email_sent", "to": to_addr, "subject": subject}
    except Exception as e:
        return {"status": "error", "error": f"SMTP error: {str(e)}"}

def interpolate_variables(config: Any, context: Dict) -> Any:
    """Substitui {{variavel}} no config com valores do contexto"""
    if isinstance(config, str):
        import re
        def replacer(match):
            key = match.group(1).strip()
            return str(get_nested_value(context, key) or match.group(0))
        return re.sub(r'\{\{(.+?)\}\}', replacer, config)
    elif isinstance(config, dict):
        return {k: interpolate_variables(v, context) for k, v in config.items()}
    elif isinstance(config, list):
        return [interpolate_variables(i, context) for i in config]
    return config


def get_nested_value(obj: Dict, path: str) -> Any:
    """Acessa valor aninhado por path (ex: 'contact.phone')"""
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def evaluate_condition(value: Any, operator: str, expected: Any) -> bool:
    """Avalia condição"""
    if operator == "equals":
        return str(value) == str(expected)
    elif operator == "not_empty":
        return bool(value) and str(value).strip() not in ("", "None", "null")
    elif operator == "is_empty":
        return not bool(value) or str(value).strip() in ("", "None", "null")
    elif operator == "contains":
        return str(expected).lower() in str(value).lower()
    elif operator == "not_equals":
        return str(value) != str(expected)
    elif operator == "greater_than":
        return float(value or 0) > float(expected or 0)
    elif operator == "less_than":
        return float(value or 0) < float(expected or 0)
    elif operator == "is_empty":
        return not value
    elif operator == "is_not_empty":
        return bool(value)
    return False
