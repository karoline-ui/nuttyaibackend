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
from langchain.memory import ConversationBufferWindowMemory
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

# Configurar Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)

# LLM principal
llm = ChatGoogleGenerativeAI(
    model=settings.GEMINI_MODEL,
    google_api_key=settings.GEMINI_API_KEY,
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
            # Buscar contact_id pelo phone
            contact = supabase.table("contacts").select("id").eq(
                "workspace_id", workspace_id
            ).eq("phone", contact_phone).single().execute()
            
            if not contact.data:
                return "❌ Contato não encontrado"
            
            result = supabase.table("appointments").insert({
                "workspace_id": workspace_id,
                "contact_id": contact.data["id"],
                "title": title,
                "start_time": start_datetime,
                "end_time": end_datetime,
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
        Verifica horários disponíveis na agenda.
        date no formato YYYY-MM-DD
        """
        try:
            # Buscar agendamentos do dia
            start = f"{date}T00:00:00"
            end = f"{date}T23:59:59"
            
            query = supabase.table("appointments").select("start_time, end_time, professional").eq(
                "workspace_id", workspace_id
            ).gte("start_time", start).lte("start_time", end).neq("status", "cancelled")
            
            if professional:
                query = query.eq("professional", professional)
            
            appointments = query.execute()
            
            # Buscar horário de funcionamento do workspace
            ws = supabase.table("workspaces").select("business_hours").eq(
                "id", workspace_id
            ).single().execute()
            
            occupied = [
                f"{a['start_time'][:16]} - {a['end_time'][:16]}"
                for a in (appointments.data or [])
            ]
            
            if not occupied:
                return f"Dia {date} está completamente livre!"
            
            return f"Horários ocupados em {date}: {', '.join(occupied)}"
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
            ).eq("workspace_id", workspace_id).single().execute()
            
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
            ).eq("phone", phone).single().execute()
            
            supabase.table("reminders").insert({
                "workspace_id": workspace_id,
                "contact_id": contact.data["id"] if contact.data else None,
                "message": message,
                "scheduled_at": scheduled_at,
                "status": "pending"
            }).execute()
            
            return f"✅ Lembrete criado para {scheduled_at}: {message}"
        except Exception as e:
            return f"❌ Erro: {str(e)}"

    return [
        schedule_appointment,
        get_available_slots,
        cancel_appointment,
        get_contact_history,
        update_contact_info,
        send_media_file,
        search_knowledge_base,
        create_reminder,
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
    ).eq("id", workspace_id).single().execute()
    
    if not ws.data:
        return {"response": "Workspace não encontrado", "actions": []}
    
    persona_name = ws.data.get("ai_persona", "Nutty")
    instructions = ws.data.get("ai_instructions", "")
    segment      = ws.data.get("segment", "")
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
    
    # Construir system prompt contextual
    system_prompt = f"""Você é {persona_name}, assistente de atendimento inteligente.
    
Segmento: {segment}
Data/hora atual: {datetime.now().strftime('%d/%m/%Y %H:%M')}

{instructions}

REGRAS IMPORTANTES:
- Responda sempre em português brasileiro
- Seja cordial, profissional e empático
- Use as ferramentas disponíveis quando necessário
- Para agendar: sempre confirme data, hora e serviço antes
- Para cancelar: confirme o agendamento antes de cancelar
- Não invente informações — use a base de conhecimento
- Se não souber algo, diga que vai verificar
- Mensagens curtas e objetivas (máximo 3 parágrafos)
- Não use markdown em mensagens (WhatsApp usa *negrito*, _itálico_)
"""
    
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
    
    agent = create_tool_calling_agent(llm, tools, prompt)
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
) -> str:
    """Gera resposta da IA para uma mensagem — usado pelo flow action.ai_respond"""
    result = await process_message(
        workspace_id=workspace_id,
        contact_phone=contact.get("phone", ""),
        conversation_id="flow",
        message_content=message,
        conversation_history=[],
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
