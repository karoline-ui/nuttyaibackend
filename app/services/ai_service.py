"""
app/services/ai_service.py
Serviço principal de IA: Gemini 2.5 Flash + LangChain
Capaz de: responder mensagens, transcrever mídia, analisar imagens,
           tomar ações (agendar, cancelar, enviar mensagem, etc.)
"""
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.tools import tool
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="google")
import google.generativeai as genai
import base64
import httpx
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import asyncio
import json

from app.core.config import settings
from app.core.database import get_supabase

# Gemini configurado por workspace - não global
def get_workspace_llm(api_key: str = None):
    """Cria LLM com a chave do workspace ou a global como fallback"""
    key = api_key or settings.GEMINI_API_KEY
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=key,
        temperature=0.7,
        streaming=True,
    )

# ══════════════════════════════════════════════
# FERRAMENTAS (Tools) que a IA pode executar
# ══════════════════════════════════════════════

def build_tools(workspace_id: str, contact_phone: str, conversation_id: str):
    """Cria tools contextualizadas para o workspace"""
    
    supabase = get_supabase()

    @tool
    def schedule_appointment(
        title: str,
        start_datetime: str,
        end_datetime: str,
        professional: str = "",
        service_type: str = "",
        notes: str = ""
    ) -> str:
        """
        Agenda uma consulta/serviço para o contato atual.
        start_datetime e end_datetime no formato ISO 8601: 2025-12-01T10:00:00
        """
        try:
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            # Converte horário de Fortaleza (UTC-3) para UTC para salvar no banco
            def to_utc(dt_str):
                try:
                    dt = _dt.fromisoformat(dt_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=_tz(_td(hours=-3)))
                    return dt.astimezone(_tz.utc).isoformat()
                except:
                    return dt_str
            start_utc = to_utc(start_datetime)
            end_utc = to_utc(end_datetime)

            # Buscar contact_id pelo phone
            contact = supabase.table("contacts").select("id").eq(
                "workspace_id", workspace_id
            ).eq("phone", contact_phone).limit(1).execute()
            
            if not contact.data:
                return "❌ Contato não encontrado"
            
            result = supabase.table("appointments").insert({
                "workspace_id": workspace_id,
                "contact_id": contact.data[0]["id"],
                "title": title,
                "start_time": start_utc,
                "end_time": end_utc,
                "professional": professional,
                "service_type": service_type,
                "notes": notes,
                "source": "ai",
                "status": "scheduled"
            }).execute()
            
            return f"✅ Agendamento criado: {title} para {start_datetime}"
        except Exception as e:
            return f"❌ Erro ao agendar: {str(e)}"

    @tool
    def get_available_slots(date: str, professional: str = "") -> str:
        """
        Verifica horários DISPONÍVEIS na agenda para agendamento.
        date no formato YYYY-MM-DD. Retorna slots livres baseado no horário comercial.
        """
        try:
            from datetime import datetime as _dt, timedelta as _td
            # Buscar agendamentos ocupados no dia
            start_of_day = f"{date}T00:00:00"
            end_of_day   = f"{date}T23:59:59"
            query = supabase.table("appointments").select("start_time, end_time").eq(
                "workspace_id", workspace_id
            ).gte("start_time", start_of_day).lte("start_time", end_of_day).neq("status", "cancelled")
            if professional:
                query = query.eq("professional", professional)
            booked = query.execute()
            occupied_ranges = []
            for a in (booked.data or []):
                try:
                    s = _dt.fromisoformat(a["start_time"][:16])
                    e = _dt.fromisoformat(a["end_time"][:16])
                    occupied_ranges.append((s.hour * 60 + s.minute, e.hour * 60 + e.minute))
                except Exception:
                    pass

            # Buscar horário comercial do workspace
            ws = supabase.table("workspaces").select("business_hours").eq("id", workspace_id).limit(1).execute()
            bh = (ws.data[0] if ws.data else {}).get("business_hours", {})
            day_names = ["sun","mon","tue","wed","thu","fri","sat"]
            try:
                weekday = _dt.strptime(date, "%Y-%m-%d").weekday()  # 0=mon
                day_key = day_names[(weekday + 1) % 7]  # adjust to sun=0
                day_hours = bh.get(day_key)
            except Exception:
                day_hours = {"open": "08:00", "close": "18:00"}

            if not day_hours:
                return f"❌ {date} é dia fechado conforme horário comercial configurado."

            open_h, open_m   = [int(x) for x in day_hours.get("open",  "08:00").split(":")]
            close_h, close_m = [int(x) for x in day_hours.get("close", "18:00").split(":")]
            open_mins  = open_h  * 60 + open_m
            close_mins = close_h * 60 + close_m

            # Gerar slots de 1 hora
            free_slots = []
            cur = open_mins
            while cur + 60 <= close_mins:
                slot_end = cur + 60
                is_free = all(not (cur < occ_end and slot_end > occ_start) for occ_start, occ_end in occupied_ranges)
                if is_free:
                    h, m = divmod(cur, 60)
                    free_slots.append(f"{h:02d}:{m:02d}")
                cur += 60

            if not free_slots:
                return f"Infelizmente {date} está totalmente ocupado. Deseja verificar outra data?"

            slots_str = ", ".join(free_slots)
            return f"Horários disponíveis em {date}: {slots_str}"
        except Exception as e:
            return f"❌ Erro ao verificar agenda: {str(e)}"

    @tool
    def cancel_appointment(appointment_id: str, reason: str = "") -> str:
        """Cancela um agendamento pelo ID"""
        try:
            supabase.table("appointments").update({
                "status": "cancelled",
                "notes": f"Cancelado via IA. Motivo: {reason}"
            }).eq("id", appointment_id).eq("workspace_id", workspace_id).execute()
            return f"✅ Agendamento {appointment_id} cancelado"
        except Exception as e:
            return f"❌ Erro ao cancelar: {str(e)}"

    @tool
    def get_contact_history(limit: int = 10) -> str:
        """Busca histórico do contato atual (últimas mensagens e agendamentos)"""
        try:
            # Últimas mensagens
            msgs = supabase.table("messages").select(
                "content, direction, created_at, is_ai"
            ).eq("workspace_id", workspace_id).eq(
                "conversation_id", conversation_id
            ).order("created_at", desc=True).limit(limit).execute()
            
            history = []
            for m in reversed(msgs.data or []):
                who = "IA" if m["is_ai"] else ("Cliente" if m["direction"] == "inbound" else "Atendente")
                history.append(f"[{m['created_at'][:16]}] {who}: {m['content']}")
            
            return "\n".join(history) if history else "Sem histórico de mensagens"
        except Exception as e:
            return f"❌ Erro: {str(e)}"

    @tool
    def update_contact_info(name: str = "", notes: str = "", tags: str = "") -> str:
        """
        Atualiza informações do contato.
        tags: lista separada por vírgulas
        """
        try:
            update_data = {}
            if name: update_data["name"] = name
            if notes: update_data["notes"] = notes
            if tags: update_data["tags"] = [t.strip() for t in tags.split(",")]
            
            if not update_data:
                return "Nenhum dado para atualizar"
            
            supabase.table("contacts").update(update_data).eq(
                "workspace_id", workspace_id
            ).eq("phone", contact_phone).execute()
            return f"✅ Contato atualizado: {update_data}"
        except Exception as e:
            return f"❌ Erro: {str(e)}"

    @tool
    def send_media_file(media_file_id: str, caption: str = "") -> str:
        """
        Envia um arquivo de mídia (imagem, PDF, etc.) para o contato.
        Busca pelo ID na base de conhecimento do workspace.
        """
        try:
            media = supabase.table("media_files").select("*").eq(
                "id", media_file_id
            ).eq("workspace_id", workspace_id).limit(1).execute()
            
            if not media.data:
                return "❌ Arquivo não encontrado"
            
            # Enfileirar envio via UazAP
            return f"✅ Arquivo '{media.data['file_name']}' enfileirado para envio"
        except Exception as e:
            return f"❌ Erro: {str(e)}"

    @tool
    def search_knowledge_base(query: str) -> str:
        """
        Busca informações na base de conhecimento do workspace.
        Use para responder perguntas sobre serviços, preços, procedimentos.
        """
        try:
            results = supabase.table("knowledge_base").select(
                "title, content"
            ).eq("workspace_id", workspace_id).eq(
                "is_active", True
            ).limit(5).execute()
            
            if not results.data:
                return "Nenhuma informação encontrada na base de conhecimento"
            
            formatted = []
            for r in results.data:
                formatted.append(f"📚 {r['title']}\n{r['content']}")
            return "\n\n".join(formatted)
        except Exception as e:
            return f"❌ Erro: {str(e)}"

    @tool
    def create_reminder(
        message: str,
        scheduled_at: str,
        contact_phone_override: str = ""
    ) -> str:
        """
        Cria um lembrete para o contato.
        scheduled_at: formato ISO 8601
        """
        try:
            phone = contact_phone_override or contact_phone
            
            contact = supabase.table("contacts").select("id").eq(
                "workspace_id", workspace_id
            ).eq("phone", phone).limit(1).execute()
            
            supabase.table("reminders").insert({
                "workspace_id": workspace_id,
                "contact_id": contact.data[0]["id"] if contact.data else None,
                "message": message,
                "scheduled_at": scheduled_at,
                "status": "pending"
            }).execute()
            
            return f"✅ Lembrete criado para {scheduled_at}: {message}"
        except Exception as e:
            return f"❌ Erro: {str(e)}"


    @tool
    def notify_doctor(subject: str, message: str) -> str:
        """
        Notifica o medico responsavel via WhatsApp.
        Use quando cliente mencionar medicamentos ou duvidas sobre tratamento.
        subject: assunto resumido. message: mensagem com dados do cliente.
        """
        try:
            import asyncio
            ws_info = supabase.table("workspaces").select("notification_phone, name").eq(
                "id", workspace_id).limit(1).execute()
            notif_phone = (ws_info.data[0] if ws_info.data else {}).get("notification_phone", "")
            if not notif_phone:
                return "Numero de notificacao nao configurado no workspace"
            ct = supabase.table("contacts").select("name").eq(
                "workspace_id", workspace_id).eq("phone", contact_phone).limit(1).execute()
            cname = (ct.data[0] if ct.data else {}).get("name", contact_phone)
            parts = ["[Notificacao - " + (ws_info.data[0] if ws_info.data else {}).get("name", "Sistema") + "]",
                     "Assunto: " + subject,
                     "Cliente: " + cname + " (" + contact_phone + ")",
                     "",
                     message]
            full_msg = "\n".join(parts)
            from app.services.whatsapp_service import WhatsAppClient
            wc = WhatsAppClient(workspace_id)
            loop = asyncio.new_event_loop()
            loop.run_until_complete(wc.send_text(notif_phone, full_msg, workspace_id))
            loop.close()
            return "Medico notificado com sucesso sobre: " + subject
        except Exception as e:
            return "Erro ao notificar medico: " + str(e)

    @tool
    def transfer_to_human(reason: str = "") -> str:
        """
        Transfere o atendimento para um humano e pausa a IA.
        Use quando cliente pedir para falar com atendente humano.
        """
        try:
            import asyncio
            ws_info = supabase.table("workspaces").select("notification_phone, name").eq(
                "id", workspace_id).limit(1).execute()
            notif_phone = (ws_info.data[0] if ws_info.data else {}).get("notification_phone", "")
            ct = supabase.table("contacts").select("name").eq(
                "workspace_id", workspace_id).eq("phone", contact_phone).limit(1).execute()
            cname = (ct.data[0] if ct.data else {}).get("name", contact_phone)
            conv = supabase.table("conversations").select("id").eq(
                "workspace_id", workspace_id).eq("contact_phone", contact_phone).limit(1).execute()
            if conv.data:
                supabase.table("conversations").update({"ai_status": "paused"}).eq(
                    "id", conv.data[0]["id"]).execute()
            if notif_phone:
                parts = ["[Transferencia para Humano - " + (ws_info.data[0] if ws_info.data else {}).get("name", "Sistema") + "]",
                         "Cliente: " + cname + " (" + contact_phone + ")",
                         "Motivo: " + (reason or "Solicitou atendente humano")]
                msg = "\n".join(parts)
                from app.services.whatsapp_service import WhatsAppClient
                wc = WhatsAppClient(workspace_id)
                loop = asyncio.new_event_loop()
                loop.run_until_complete(wc.send_text(notif_phone, msg, workspace_id))
                loop.close()
            return "transferencia_humano"
        except Exception as e:
            return "Erro na transferencia: " + str(e)

    return [
        schedule_appointment,
        get_available_slots,
        cancel_appointment,
        get_contact_history,
        update_contact_info,
        send_media_file,
        search_knowledge_base,
        get_next_available_slots,
        create_reminder,
        notify_doctor,
        transfer_to_human,
    ]


# ══════════════════════════════════════════════
# CONSTRUTOR DO AGENTE
# ══════════════════════════════════════════════

async def process_message(
    workspace_id: str,
    contact_phone: str,
    conversation_id: str,
    message_content: str,
    message_type: str = "text",
    media_data: Optional[bytes] = None,
    media_mime: Optional[str] = None,
    conversation_history: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    """
    Processa uma mensagem e retorna a resposta da IA + ações tomadas
    """
    supabase_client = get_supabase()
    
    # Buscar configurações do workspace
    ws = supabase_client.table("workspaces").select(
        "ai_persona, ai_instructions, settings, segment, niche"
    ).eq("id", workspace_id).limit(1).execute()
    
    if not ws.data:
        return {"response": "Workspace não encontrado", "actions": []}
    
    persona_name = (ws.data[0] if ws.data else {}).get("ai_persona", "Nutty")
    instructions = (ws.data[0] if ws.data else {}).get("ai_instructions", "")
    segment      = (ws.data[0] if ws.data else {}).get("segment", "")
    # API key: busca da conexão Gemini ativa do workspace, senão usa a global do .env
    ws_api_key = settings.GEMINI_API_KEY
    try:
        conn = supabase_client.table("connections").select("config").eq(
            "workspace_id", workspace_id
        ).eq("type", "gemini").eq("is_active", True).limit(1).execute()
        if conn.data and conn.data[0].get("config", {}).get("api_key"):
            ws_api_key = conn.data[0]["config"]["api_key"]
    except Exception:
        pass
    if ws_api_key != settings.GEMINI_API_KEY:
        import warnings
        warnings.filterwarnings("ignore", category=FutureWarning, module="google")
        import google.generativeai as _genai
        _genai.configure(api_key=ws_api_key)
    
    # Carrega knowledge_base do workspace
    kb_content = ""
    try:
        kb = supabase_client.table("knowledge_base").select("title, content").eq(
            "workspace_id", workspace_id).eq("is_active", True).execute()
        if kb.data:
            kb_parts = ["## " + r["title"] + "\n" + r["content"] for r in kb.data]
            kb_content = "\n\n".join(kb_parts)
        print(f"[KB] {len(kb.data if kb.data else [])} registros, {len(kb_content)} chars")
    except Exception as kb_err:
        print(f"[KB] erro: {kb_err}")

    weekday_pt = ["segunda-feira","terca-feira","quarta-feira","quinta-feira","sexta-feira","sabado","domingo"][datetime.now().weekday()]
    kb_block = ("\n\nBASE DE CONHECIMENTO (use sempre para precos e servicos):\n" + kb_content) if kb_content else ""

    # Construir system prompt contextual
    system_prompt = (
        "Voce e " + persona_name + ", assistente de atendimento.\n"
        "Segmento: " + segment + "\n"
        "Data/hora: " + datetime.now().strftime("%d/%m/%Y %H:%M") + " (" + weekday_pt + ")\n\n"
        + instructions
        + kb_block
        + "\n\nREGRAS:\n"
        "- Responda em portugues\n"
        "- Para precos e servicos: use SEMPRE a BASE DE CONHECIMENTO acima\n"
        "- Para sugerir horarios: use SEMPRE get_next_available_slots antes\n"
        "- NUNCA invente horarios - use apenas os retornados pela tool\n"
        "- NUNCA diga que nao tem acesso a precos - eles estao na base acima\n"
        "- Sempre que souber o nome do cliente, chame update_contact_info\n"
        "- NUNCA invente valores\n"
        "- Nao use markdown\n"
    )
    # Preparar conteúdo da mensagem
    if message_type in ["audio", "video"] and media_data:
        # Transcrição via Gemini Vision
        transcription = await transcribe_media(media_data, media_mime, message_type)
        message_content = f"[Transcrição de {message_type}]: {transcription}"
    
    elif message_type == "image" and media_data:
        # Análise de imagem via Gemini Vision
        image_description = await analyze_image(media_data, media_mime, message_content)
        message_content = f"[Imagem enviada]: {image_description}"
    
    elif message_type == "document" and media_data:
        # Extração de texto do PDF
        pdf_text = await extract_pdf_text(media_data)
        message_content = f"[Documento PDF]: {pdf_text[:2000]}"
    
    # Construir histórico de conversa
    chat_history = []
    if conversation_history:
        for msg in conversation_history[-20:]:  # últimas 20 msgs (10 trocas)
            if msg["direction"] == "inbound":
                chat_history.append(HumanMessage(content=msg["content"]))
            else:
                chat_history.append(AIMessage(content=msg["content"]))
    
    # Criar tools e agente
    tools = build_tools(workspace_id, contact_phone, conversation_id)
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{input}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ])
    
    ws_llm = get_workspace_llm(ws_api_key)
    agent = create_tool_calling_agent(ws_llm, tools, prompt)
    agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        max_iterations=5,
        return_intermediate_steps=True,
    )
    
    try:
        result = await agent_executor.ainvoke({
            "input": message_content,
            "chat_history": chat_history,
        })
        
        # Extrair ações tomadas
        actions = []
        for step in result.get("intermediate_steps", []):
            if len(step) >= 2:
                tool_name = step[0].tool if hasattr(step[0], 'tool') else str(step[0])
                tool_result = str(step[1])
                actions.append({"tool": tool_name, "result": tool_result})
        
        return {
            "response": result["output"],
            "actions": actions,
            "model": settings.GEMINI_MODEL,
        }
    except Exception as e:
        print(f"AI Error: {e}")
        return {
            "response": "Desculpe, tive um problema. Um atendente irá te ajudar em breve.",
            "actions": [],
            "error": str(e),
        }


# ══════════════════════════════════════════════
# PROCESSAMENTO DE MÍDIA
# ══════════════════════════════════════════════

async def transcribe_media(
    media_data: bytes,
    mime_type: str,
    media_type: str
) -> str:
    """Transcreve áudio/vídeo usando Gemini Vision"""
    try:
        prompt = "Transcreva o conteúdo deste áudio/vídeo em português. Seja preciso."
        
        model_obj = genai.GenerativeModel(settings.GEMINI_VISION_MODEL)
        response = model_obj.generate_content([prompt, {"mime_type": mime_type, "data": base64.b64encode(media_data).decode()}])
        return response.text
    except Exception as e:
        return f"[Não foi possível transcrever: {str(e)}]"


async def analyze_image(
    image_data: bytes,
    mime_type: str,
    user_caption: str = ""
) -> str:
    """Analisa imagem usando Gemini Vision"""
    try:
        model = genai.GenerativeModel(settings.GEMINI_VISION_MODEL)
        
        prompt = f"Descreva detalhadamente esta imagem em português. Contexto do usuário: '{user_caption}'"
        
        response = model.generate_content([
            prompt,
            {"mime_type": mime_type, "data": base64.b64encode(image_data).decode()}
        ])
        return response.text
    except Exception as e:
        return f"[Não foi possível analisar a imagem: {str(e)}]"


async def extract_pdf_text(pdf_data: bytes) -> str:
    """Extrai texto de PDF usando PyMuPDF"""
    try:
        import fitz  # PyMuPDF
        import io
        
        doc = fitz.open(stream=pdf_data, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text[:5000]  # limitar tamanho
    except Exception as e:
        return f"[Não foi possível extrair o PDF: {str(e)}]"


async def generate_conversation_summary(messages: List[Dict]) -> str:
    """Gera resumo do contexto da conversa para economizar tokens"""
    if len(messages) < 10:
        return ""
    
    history_text = "\n".join([
        f"{'Cliente' if m['direction']=='inbound' else 'IA'}: {m['content']}"
        for m in messages[-20:]
    ])
    
    model = genai.GenerativeModel(settings.GEMINI_MODEL)
    response = model.generate_content(
        f"Faça um resumo MUITO conciso (3 linhas) desta conversa de atendimento:\n\n{history_text}"
    )
    return response.text


# ══════════════════════════════════════════════
# FUNÇÕES AUXILIARES usadas pelos flows
# ══════════════════════════════════════════════

async def generate_ai_response(
    message: str,
    contact: dict,
    workspace_id: str,
    context_override: str = None,
    conversation_id: str = None,
) -> str:
    """Gera resposta da IA para uma mensagem - usado pelo flow action.ai_respond"""
    from app.core.database import get_supabase
    supabase = get_supabase()

    # Busca conversa real do contato
    real_conv_id = conversation_id
    if not real_conv_id:
        contact_phone = contact.get("phone", "")
        contact_result = supabase.table("contacts").select("id").eq(
            "workspace_id", workspace_id).eq("phone", contact_phone).limit(1).execute()
        if contact_result.data:
            contact_id = contact_result.data[0]["id"]
            conv_result = supabase.table("conversations").select("id").eq(
                "workspace_id", workspace_id).eq("contact_id", contact_id).limit(1).execute()
            if conv_result.data:
                real_conv_id = conv_result.data[0]["id"]

    # Busca histórico real da conversa
    history = []
    if real_conv_id:
        msgs = supabase.table("messages").select("content, direction, is_ai").eq(
            "conversation_id", real_conv_id
        ).order("created_at", desc=True).limit(20).execute()
        for m in reversed(msgs.data or []):
            history.append({
                "direction": m.get("direction", "inbound"),
                "content": m.get("content", ""),
            })

    result = await process_message(
        workspace_id=workspace_id,
        contact_phone=contact.get("phone", ""),
        conversation_id=real_conv_id or "flow",
        message_content=message,
        conversation_history=history,
    )
    response = result.get("response", "")
    if context_override:
        # Re-run com contexto extra
        try:
            result2 = await process_message(
                workspace_id=workspace_id,
                contact_phone=contact.get("phone", ""),
                conversation_id="flow",
                message_content=f"[CONTEXTO EXTRA: {context_override}]\n{message}",
                conversation_history=[],
            )
            response = result2.get("response", response)
        except Exception:
            pass
    return response


async def classify_message(message: str, categories: list, workspace_id: str) -> str:
    """Classifica mensagem em uma das categorias usando IA"""
    try:
        import google.generativeai as genai
        from app.core.config import settings
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        cats = ", ".join(categories)
        prompt = f"""Classifique a mensagem abaixo em EXATAMENTE UMA das categorias: {cats}
Responda APENAS com o nome da categoria, sem explicações.
Mensagem: "{message}"
Categoria:"""
        response = model.generate_content(prompt)
        result = response.text.strip().lower()
        # Garante que o resultado é uma das categorias
        for cat in categories:
            if cat.lower() in result:
                return cat.lower()
        return categories[0] if categories else "outro"
    except Exception as e:
        return categories[0] if categories else "erro"


async def extract_entities(message: str, fields: str, workspace_id: str) -> dict:
    """Extrai entidades específicas de uma mensagem"""
    try:
        import google.generativeai as genai, json
        from app.core.config import settings
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        prompt = f"""Extraia as seguintes informações da mensagem: {fields}
Responda em JSON puro, sem markdown. Se não encontrar, use null.
Mensagem: "{message}"
JSON:"""
        response = model.generate_content(prompt)
        text = response.text.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception:
        return {}


async def summarize_conversation(phone: str, workspace_id: str, max_lines: int = 5) -> str:
    """Resume o histórico de conversa de um contato"""
    try:
        from app.core.database import get_supabase
        import google.generativeai as genai
        from app.core.config import settings
        supabase = get_supabase()
        conv = supabase.table("conversations").select("id").eq(
            "workspace_id", workspace_id).eq("contact_phone", phone).limit(1).execute()
        if not conv.data:
            return "Sem histórico disponível"
        msgs = supabase.table("messages").select("content,direction").eq(
            "conversation_id", conv.data[0]["id"]).order("created_at", desc=True).limit(20).execute()
        if not msgs.data:
            return "Sem mensagens anteriores"
        history = "\n".join([
            f"{'Cliente' if m['direction']=='inbound' else 'IA'}: {m['content']}"
            for m in reversed(msgs.data)
        ])
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        response = model.generate_content(
            f"Resuma em {max_lines} linhas esta conversa de atendimento:\n{history}")
        return response.text.strip()
    except Exception as e:
        return f"Erro ao resumir: {str(e)}"


async def analyze_sentiment(message: str, workspace_id: str) -> str:
    """Analisa o sentimento de uma mensagem"""
    try:
        import google.generativeai as genai
        from app.core.config import settings
        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel(settings.GEMINI_MODEL)
        prompt = f"""Analise o sentimento desta mensagem e responda com APENAS UMA PALAVRA:
positivo, negativo, neutro, frustrado, urgente, satisfeito ou ansioso.
Mensagem: "{message}"
Sentimento:"""
        response = model.generate_content(prompt)
        return response.text.strip().lower().split()[0]
    except Exception:
        return "neutro"