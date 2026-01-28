"""
Cliente LLM del orquestador (OpenAI). Carga y usa el agente orquestador.
"""

from typing import Optional, Tuple

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

try:
    from . import config as app_config
    from .models import OrquestradorDecision
    from .logging_config import get_logger
except ImportError:
    import config as app_config
    from models import OrquestradorDecision
    from logging_config import get_logger

logger = get_logger("llm")
_llm: Optional[ChatOpenAI] = None
_structured_llm: Optional[ChatOpenAI] = None


def _get_llm() -> ChatOpenAI:
    """Lazy init del LLM (OpenAI) estándar."""
    global _llm
    if _llm is None:
        key = app_config.OPENAI_API_KEY
        if not key:
            raise ValueError(
                "OPENAI_API_KEY no configurada"
            )
        _llm = ChatOpenAI(
            api_key=key,
            model=app_config.OPENAI_MODEL,
            temperature=0.4,
            max_tokens=4096,
            timeout=app_config.OPENAI_TIMEOUT,
        )
    return _llm


def _get_structured_llm() -> ChatOpenAI:
    """
    Lazy init del LLM con structured output.
    Usa .with_structured_output() para retornar JSON según el schema OrquestradorDecision.
    """
    global _structured_llm
    if _structured_llm is None:
        llm = _get_llm()
        _structured_llm = llm.with_structured_output(OrquestradorDecision)
    return _structured_llm


async def invoke_orquestador(system_prompt: str, message: str) -> Tuple[str, Optional[str]]:
    """
    Invoca el agente orquestador (OpenAI) con system prompt y mensaje del usuario.
    Usa structured output para obtener decisión estructurada (delegar o responder).

    Args:
        system_prompt: Prompt del sistema (identidad, reglas, frases).
        message: Mensaje del cliente.

    Returns:
        Tupla (respuesta, agente_a_invocar):
        - respuesta: Respuesta del orquestador (texto)
        - agente_a_invocar: "venta", "cita", "reserva" o None si responde directamente
    """
    structured_llm = _get_structured_llm()
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=message),
    ]
    
    # Invocar con structured output: retorna OrquestradorDecision
    decision: OrquestradorDecision = await structured_llm.ainvoke(messages)
    
    logger.info(
        "Decisión estructurada: action=%s, agent=%s",
        decision.action, decision.agent_name
    )
    
    # Extraer respuesta y agente
    reply = decision.response
    agent_to_invoke = decision.agent_name if decision.action == "delegate" else None
    
    return reply, agent_to_invoke
