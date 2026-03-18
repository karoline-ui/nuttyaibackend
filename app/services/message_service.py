"""
app/services/message_service.py
Helpers para salvar e buscar mensagens/conversas
"""
from app.core.database import get_supabase
from datetime import datetime

async def get_conversation(workspace_id: str, contact_id: str) -> dict:
    """Busca ou cria conversa para o contato"""
    supabase = get_supabase()

    existing = supabase.table("conversations").select("*").eq(
        "workspace_id", workspace_id
    ).eq("contact_id", contact_id).limit(1).execute()

    if existing.data:
        return existing.data[0]

    # Criar nova conversa
    new_conv = supabase.table("conversations").insert({
        "workspace_id": workspace_id,
        "contact_id": contact_id,
        "ai_status": "active",
        "status": "open",
    }).execute()

    return new_conv.data[0] if new_conv.data else {}

async def save_message(workspace_id: str, conversation_id: str, msg_data: dict) -> dict:
    """Salva mensagem e atualiza preview da conversa"""
    supabase = get_supabase()

    result = supabase.table("messages").insert({
        "workspace_id": workspace_id,
        "conversation_id": conversation_id,
        **msg_data,
    }).execute()

    # Atualizar preview da conversa
    content = msg_data.get("content", "")
    if msg_data.get("type") == "audio":
        content = "🎵 Áudio"
    elif msg_data.get("type") == "image":
        content = "📷 Imagem"
    elif msg_data.get("type") == "video":
        content = "🎥 Vídeo"
    elif msg_data.get("type") == "document":
        content = "📄 Documento"

    supabase.table("conversations").update({
        "last_message": content[:100] if content else "",
        "last_message_at": datetime.now().isoformat(),
    }).eq("id", conversation_id).execute()

    return result.data[0] if result.data else {}


async def handle_incoming_message(
    workspace_id: str,
    phone: str,
    content: str,
    message_type: str = "text",
    media_data: bytes = None,
    media_mime: str = None,
    raw_payload: dict = None,
):
    """
    Ponto central de entrada de mensagens reais do WhatsApp.
    1. Cria/busca contato
    2. Cria/busca conversa
    3. Salva mensagem recebida
    4. Verifica flows ativos com gatilho message_received
    5. Se nenhum flow ativo, usa IA diretamente
    6. Salva e envia resposta
    """
    from app.services.whatsapp_service import whatsapp_client
    from app.services.ai_service import process_message as ai_process
    from app.api.v1.flows import run_flow
    supabase = get_supabase()

    # 1. Busca ou cria contato
    contact_result = supabase.table("contacts").select("*").eq(
        "workspace_id", workspace_id).eq("phone", phone).limit(1).execute()

    if contact_result.data:
        contact = contact_result.data[0]
    else:
        new_contact = supabase.table("contacts").insert({
            "workspace_id": workspace_id,
            "phone": phone,
            "name": phone,
            "tags": ["novo"],
        }).execute()
        contact = new_contact.data[0] if new_contact.data else {"id": None, "phone": phone, "name": phone, "tags": []}

    contact_id = contact.get("id")

    # 2. Busca ou cria conversa
    conversation = await get_conversation(workspace_id, contact_id)
    conversation_id = conversation.get("id")

    # 3. Deduplicação — evita processar a mesma mensagem duas vezes
    if raw_payload:
        ext_id = raw_payload.get("data", {}).get("key", {}).get("id", "")
        if ext_id:
            existing = supabase.table("messages").select("id").eq(
                "workspace_id", workspace_id
            ).eq("external_id", ext_id).limit(1).execute()
            if existing.data:
                return  # já processada

    # Salva mensagem recebida
    await save_message(workspace_id, conversation_id, {
        "contact_id":   contact_id,
        "direction":    "inbound",
        "content":      content or f"[{message_type}]",
        "type":         message_type,
        "is_ai":        False,
        "created_at":   datetime.now().isoformat(),
    })

    # 4. Verifica estado da conversa
    ai_status = conversation.get("ai_status", "active")

    # 4a. Aguardando confirmação de consulta (botão SIM/NÃO)
    if ai_status == "waiting_confirmation":
        apt_id = conversation.get("waiting_appointment", "")
        btn_id = content.strip().lower()
        confirmed = any(x in btn_id for x in ["confirmo", "sim", "yes", "apt_yes"])
        declined  = any(x in btn_id for x in ["remarcar", "nao", "no", "apt_no", "cancel"])
        if confirmed and apt_id:
            supabase.table("appointments").update({"status": "confirmed"}).eq("id", apt_id).execute()
            supabase.table("conversations").update({
                "ai_status": "active", "waiting_appointment": None
            }).eq("id", conversation_id).execute()
            from app.services.whatsapp_service import whatsapp_client as wc
            await wc.send_text(phone, "Consulta confirmada! Te esperamos. Qualquer duvida estamos aqui.", workspace_id)
            return
        elif declined and apt_id:
            supabase.table("appointments").update({"status": "pending_reschedule"}).eq("id", apt_id).execute()
            supabase.table("conversations").update({
                "ai_status": "active", "waiting_appointment": None
            }).eq("id", conversation_id).execute()
            from app.services.whatsapp_service import whatsapp_client as wc
            await wc.send_text(phone, "Entendido! Qual data e horario seria melhor para voce?", workspace_id)
            return
        else:
            # Resposta ambigua — devolve para IA processar normalmente
            supabase.table("conversations").update({
                "ai_status": "active", "waiting_appointment": None
            }).eq("id", conversation_id).execute()

    # 4b. Aguardando input de collect_data — retoma o flow com a resposta
    if ai_status == "waiting_input":
        variable = conversation.get("waiting_for_variable", "resposta")
        flow_node_id = conversation.get("waiting_flow_id", "")
        validation = conversation.get("waiting_validation", "none")

        # Valida resposta se necessário
        valid = True
        if validation == "not_empty" and not content.strip():
            valid = False
        elif validation == "is_number" and not content.strip().replace(".", "").replace(",", "").isdigit():
            valid = False
        elif validation == "is_phone" and len(content.strip().replace(" ","").replace("-","")) < 8:
            valid = False

        if not valid:
            from app.services.whatsapp_service import whatsapp_client as wc
            await wc.send_text(phone, "Por favor, envie uma resposta válida.", workspace_id)
            return

        # Limpa estado de espera
        supabase.table("conversations").update({
            "ai_status": "active",
            "waiting_for_variable": None,
            "waiting_flow_id": None,
            "waiting_validation": None,
        }).eq("id", conversation_id).execute()

        # Retoma o flow com a variável coletada
        flows_r = supabase.table("flows").select("*").eq(
            "workspace_id", workspace_id
        ).eq("is_active", True).execute()
        for flow in (flows_r.data or []):
            # Injeta a variável coletada e retoma
            ctx = {
                "trigger_data": {"message": content, "phone": phone},
                "contact": {"phone": phone, "name": contact.get("name",""), "tags": contact.get("tags",[]), "id": contact_id},
                "message": {"content": content, "type": message_type},
                "variables": {f"_collected_{variable}": content, variable: content},
                "_simulating": False,
                "_resuming_after_collect": flow_node_id,
            }
            try:
                from app.api.v1.flows import run_flow
                await run_flow(flow["id"], workspace_id, ctx)
            except Exception as e:
                import logging; logging.error(f"Flow resume error: {e}")
        return

    # 4b. IA pausada — atendimento humano
    if ai_status == "paused":
        return  # Atendimento humano ativo — não responder

    # 5. Seleciona o flow correto com prioridade de triggers
    # Ordem: keyword > button_clicked > new_contact > message_received
    all_flows = supabase.table("flows").select("*").eq(
        "workspace_id", workspace_id
    ).eq("is_active", True).execute()

    matched_flow = None
    trigger_data = {
        "message": content, "phone": phone, "type": message_type,
        "contact_id": contact_id, "is_new_contact": False
    }

    if all_flows.data:
        # 1. Tenta keyword match primeiro
        for flow in all_flows.data:
            nodes = flow.get("nodes", [])
            for node in nodes:
                nd = node.get("data", {})
                if nd.get("nodeType") == "trigger.keyword":
                    kw = nd.get("config", {}).get("keyword", "").strip().lower()
                    mode = nd.get("config", {}).get("mode", "contains")
                    msg_lower = content.lower()
                    if kw and (
                        (mode == "contains" and kw in msg_lower) or
                        (mode == "exact" and kw == msg_lower) or
                        (mode == "starts_with" and msg_lower.startswith(kw))
                    ):
                        matched_flow = flow
                        break
            if matched_flow:
                break

        # 2. message_received genérico
        if not matched_flow:
            for flow in all_flows.data:
                nodes = flow.get("nodes", [])
                for node in nodes:
                    if node.get("data", {}).get("nodeType") == "trigger.message_received":
                        matched_flow = flow
                        break
                if matched_flow:
                    break

    if matched_flow:
        context = {
            "trigger_data": trigger_data,
            "contact":      {"phone": phone, "name": contact.get("name", ""), "tags": contact.get("tags", []), "id": contact_id},
            "message":      {"content": content, "type": message_type},
            "variables":    {},
            "_simulating":  False,
        }
        try:
            await run_flow(matched_flow["id"], workspace_id, context)
        except Exception as e:
            import logging
            logging.error(f"Flow execution error: {e}")
        return

    # 6. Sem flow — usa IA diretamente
    # Busca histórico recente
    history_result = supabase.table("messages").select(
        "content, direction, is_ai"
    ).eq("conversation_id", conversation_id).order(
        "created_at", desc=True
    ).limit(20).execute()

    history = list(reversed(history_result.data or []))

    ai_result = await ai_process(
        workspace_id=workspace_id,
        contact_phone=phone,
        conversation_id=conversation_id,
        message_content=content,
        message_type=message_type,
        media_data=media_data,
        media_mime=media_mime,
        conversation_history=history,
    )

    response_text = ai_result.get("response", "")
    if not response_text:
        return

    # 7. Envia resposta (delay anti-spam: 1-2s humaniza e evita ban)
    import asyncio, random
    await asyncio.sleep(random.uniform(1.0, 2.5))
    await whatsapp_client.send_text(phone, response_text, workspace_id)

    # 8. Salva resposta da IA
    await save_message(workspace_id, conversation_id, {
        "contact_id":   contact_id,
        "direction":    "outbound",
        "content":      response_text,
        "type":         "text",
        "is_ai":        True,
        "created_at":   datetime.now().isoformat(),
    })