"""
Cliente LLM del orquestador (OpenAI). Carga y usa el agente orquestador.
Inicialización lazy protegida con asyncio.Lock para concurrencia segura.
"""

import asyncio
from typing import Optional, Tuple

import openai
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

try:
    from ..config import config as app_config
    from ..config.models import OrquestradorDecision
    from ..infrastructure.logging_config import get_logger
except ImportError:
    from orquestador.config import config as app_config
    from orquestador.config.models import OrquestradorDecision
    from orquestador.infrastructure.logging_config import get_logger

logger = get_logger("llm")
_llm: Optional[ChatOpenAI] = None
_structured_llm: Optional[ChatOpenAI] = None
_llm_lock = asyncio.Lock()


def _create_llm_if_needed() -> None:
    """Crea _llm si no existe. Llamar solo desde dentro de _llm_lock."""
    global _llm
    if _llm is None:
        key = app_config.OPENAI_API_KEY
        if not key:
            raise ValueError("OPENAI_API_KEY no configurada")
        _llm = ChatOpenAI(
            api_key=key,
            model=app_config.OPENAI_MODEL,
            temperature=0.4,
            max_tokens=4096,
            timeout=app_config.OPENAI_TIMEOUT,
        )


async def _get_structured_llm() -> ChatOpenAI:
    """
    Lazy init del LLM con structured output.
    Usa .with_structured_output() para retornar JSON según el schema OrquestradorDecision.
    Protegido con lock para evitar race en init concurrente.
    """
    global _structured_llm
    async with _llm_lock:
        if _structured_llm is None:
            _create_llm_if_needed()
            _structured_llm = _llm.with_structured_output(OrquestradorDecision)
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
    structured_llm = await _get_structured_llm()
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=message),
    ]
    
    # Invocar con structured output: retorna OrquestradorDecision
    try:
        decision: OrquestradorDecision = await structured_llm.ainvoke(messages)
    except asyncio.TimeoutError:
        logger.error("Timeout invocando OpenAI (>%ss)", app_config.OPENAI_TIMEOUT)
        raise RuntimeError("OpenAI no respondió a tiempo")
    except openai.AuthenticationError as e:
        logger.error("API key inválida o sin permisos: %s", e)
        raise ValueError("OPENAI_API_KEY inválida o expirada")
    except openai.RateLimitError as e:
        logger.warning("Rate limit de OpenAI alcanzado: %s", e)
        raise RuntimeError("Límite de OpenAI alcanzado, intenta de nuevo")
    except openai.APIConnectionError as e:
        logger.error("Sin conexión a OpenAI: %s", e)
        raise RuntimeError("No se pudo conectar a OpenAI")
    except openai.APIStatusError as e:
        logger.error("Error HTTP de OpenAI status=%s: %s", e.status_code, e)
        raise RuntimeError(f"OpenAI retornó error {e.status_code}")
    except ValidationError as e:
        logger.error("Structured output no válido: %s", e)
        raise RuntimeError("Respuesta de OpenAI no tiene el formato esperado")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception("Error inesperado invocando OpenAI: %s", type(e).__name__)
        raise

    logger.info(
        "Decisión estructurada: action=%s, agent=%s",
        decision.action, decision.agent_name
    )

    # Extraer respuesta y agente
    reply = decision.response
    agent_to_invoke = decision.agent_name if decision.action == "delegate" else None

    return reply, agent_to_invoke
