"""
app/api/v1/messages.py
"""
from fastapi import APIRouter, HTTPException
from app.core.database import get_supabase
router = APIRouter()

@router.get("")
async def list_messages(workspace_id: str, conversation_id: str, limit: int = 50):
    supabase = get_supabase()
    result = supabase.table("messages").select("*").eq(
        "workspace_id", workspace_id
    ).eq("conversation_id", conversation_id).order("created_at", desc=True).limit(limit).execute()
    return list(reversed(result.data or []))


@router.post("/chat-test")
async def chat_test(workspace_id: str, body: dict):
    """
    Chat direto com a IA — sem executar flow.
    Mantém histórico da sessão para conversa contínua.
    """
    from app.services.ai_service import process_message

    message = body.get("message", "")
    session_history = body.get("session_history", [])

    if not message.strip():
        raise HTTPException(status_code=400, detail="Mensagem vazia")

    try:
        ai_result = await process_message(
            workspace_id=workspace_id,
            contact_phone="test_0000000000",
            conversation_id=f"chattest_{workspace_id}",
            message_content=message,
            conversation_history=session_history,
        )
        response = ai_result.get("response", "")

        # Acumula histórico
        updated_history = list(session_history)
        updated_history.append({"content": message,  "direction": "inbound"})
        updated_history.append({"content": response, "direction": "outbound"})
        # Limita a 30 mensagens
        if len(updated_history) > 30:
            updated_history = updated_history[-30:]

        return {
            "response": response,
            "session_history": updated_history,
        }
    except Exception as e:
        import logging
        logging.error(f"chat-test error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
