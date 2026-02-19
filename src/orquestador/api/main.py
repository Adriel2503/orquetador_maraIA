"""FastAPI app principal del orquestador"""

import asyncio
import json as _json_mod
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

from cachetools import TTLCache

# Permitir ejecución directa con python main.py
# Si se ejecuta directamente (no como módulo), ajustar el path
# __package__ será None cuando se ejecuta directamente con python main.py
if __package__ is None:
    # Agregar el directorio actual al path para importaciones absolutas
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

# Importación que funciona tanto como módulo como script directo
try:
    from ..config.models import ChatRequest, ChatResponse
    from ..config import config as app_config
    from ..prompts import build_orquestador_system_prompt_with_memory, modalidad_to_agent
    from ..integrations.llm import invoke_orquestador
    from ..integrations.mcp_client import invoke_mcp_agent, get_circuit_breaker_states
    from ..services.memory import memory_manager
    from ..infrastructure.logging_config import get_logger
    from ..infrastructure import metrics as app_metrics
except ImportError:
    from orquestador.config.models import ChatRequest, ChatResponse
    from orquestador.config import config as app_config
    from orquestador.prompts import build_orquestador_system_prompt_with_memory, modalidad_to_agent
    from orquestador.integrations.llm import invoke_orquestador
    from orquestador.integrations.mcp_client import invoke_mcp_agent, get_circuit_breaker_states
    from orquestador.services.memory import memory_manager
    from orquestador.infrastructure.logging_config import get_logger
    from orquestador.infrastructure import metrics as app_metrics

logger = get_logger("main")

# Cache con TTL y límite de tamaño para evitar memory leak en producción multiempresa.
# maxsize=500 → máximo 500 empresas en memoria simultáneamente (LRU eviction al superar límite)
# ttl=3600    → cada entrada expira automáticamente a la 1 hora (evita datos obsoletos)
_contexto_cache: TTLCache = TTLCache(maxsize=500, ttl=3600)  # id_empresa -> contexto (str)

# Circuit breaker: también acotado con TTL (5 min) para auto-reset de fallos antiguos
_contexto_failures: TTLCache = TTLCache(maxsize=500, ttl=300)  # id_empresa -> failure_count (int)
_contexto_failure_threshold = 3


def _is_contexto_circuit_open(id_empresa: int) -> bool:
    """Verifica si el circuit breaker para contexto está abierto.
    
    TTLCache expira automáticamente entradas viejas (ttl=300s),
    por lo que no necesitamos comparar timestamps manualmente.
    """
    failure_count = _contexto_failures.get(id_empresa, 0)
    return failure_count >= _contexto_failure_threshold


def _fetch_contexto_negocio_sync(id_empresa: int) -> Optional[str]:
    """
    Obtiene contexto de negocio con cache TTL + circuit breaker + retry con backoff.
    Cachea incluso contexto vacío para evitar thrashing.
    Se ejecuta en un thread separado (via asyncio.to_thread).
    
    TTLCache garantiza:
    - Máximo 500 empresas en memoria (LRU eviction)
    - Expiración automática a la 1 hora sin limpiezas manuales
    """
    # 1. Verificar cache: TTLCache expira automáticamente, no necesitamos timestamp manual
    if id_empresa in _contexto_cache:
        contexto = _contexto_cache[id_empresa]
        logger.debug(
            "Contexto desde cache para id_empresa=%s (valor=%s)",
            id_empresa, "vacío" if not contexto else "presente"
        )
        return contexto if contexto else None

    # 2. Verificar circuit breaker
    if _is_contexto_circuit_open(id_empresa):
        logger.warning("Circuit abierto para contexto de negocio id_empresa=%s", id_empresa)
        return None

    # 3. Retry con backoff exponencial (hasta 2 intentos)
    max_retries = 2

    for attempt in range(max_retries):
        try:
            url = app_config.CONTEXTO_NEGOCIO_ENDPOINT
            body = _json_mod.dumps({"codOpe": "OBTENER_CONTEXTO_NEGOCIO", "id_empresa": id_empresa}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=app_config.CONTEXTO_NEGOCIO_TIMEOUT) as resp:
                data = _json_mod.loads(resp.read().decode())
                if data.get("success"):
                    contexto = data.get("contexto_negocio") or ""
                    # TTLCache almacena y expira automáticamente en 1 hora
                    _contexto_cache[id_empresa] = contexto
                    # Reset circuit breaker al tener éxito
                    _contexto_failures.pop(id_empresa, None)
                    return contexto if contexto else None
        except Exception as e:
            logger.debug(
                "Error obteniendo contexto intento %d/%d id_empresa=%s: %s",
                attempt + 1, max_retries, id_empresa, e
            )
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # backoff: 1s, 2s

    # Todos los intentos fallaron: incrementar contador del circuit breaker
    logger.debug("Todos los intentos fallaron para contexto id_empresa=%s", id_empresa)
    current_failures = _contexto_failures.get(id_empresa, 0)
    # TTLCache resetea automáticamente el contador luego de ttl=300s
    _contexto_failures[id_empresa] = current_failures + 1

    return None


# CORS - desde env o * como fallback (en producción especificar dominios)
_cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",")
_cors_origins = [o.strip() for o in _cors_origins if o.strip()]

app = FastAPI(
    title="MaravIA Orquestador",
    description="Orquestador que enruta conversaciones a agentes especializados MCP (Venta, Cita, Reserva)",
    version=app_config.VERSION
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,  # ["https://app.maravia.pe", "https://n8n.maravia.pe"] en producción
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _process_chat(request: ChatRequest) -> ChatResponse:
    """Lógica completa del flujo chat: memoria, contexto, OpenAI, MCP y guardado."""
    start_time = time.perf_counter()
    request_dict = request.model_dump()
    logger.info(
        "POST /api/agent/chat request",
        extra={"extra_fields": {
            "request_message": request.message,
            "session_id": request.session_id,
            "nombre_bot": request.config.nombre_bot,
            "id_empresa": request.config.id_empresa,
            "mcp_reserva_url": app_config.MCP_RESERVA_URL,
            "openai_model": app_config.OPENAI_MODEL,
        }}
    )
    logger.debug("Request body: %s", _json_mod.dumps(request_dict, ensure_ascii=False))

    # 1. CARGAR MEMORIA (historial de conversación)
    memory = await memory_manager.get(request.session_id, limit=10)
    logger.info("Memoria cargada", extra={"extra_fields": {"session_id": request.session_id, "turnos": len(memory)}})
    current_agent = None
    if memory:
        current_agent = await memory_manager.get_current_agent(request.session_id)
        if current_agent:
            logger.info("Agente activo en sesión", extra={"extra_fields": {"session_id": request.session_id, "agent": current_agent}})

    # 2. Obtener contexto de negocio (para responder preguntas básicas sin delegar)
    contexto_negocio = None
    try:
        contexto_negocio = await asyncio.wait_for(
            asyncio.to_thread(_fetch_contexto_negocio_sync, request.config.id_empresa),
            timeout=app_config.CONTEXTO_NEGOCIO_TIMEOUT + 2  # +2s para overhead de thread pool
        )
    except asyncio.TimeoutError:
        logger.warning("Timeout obteniendo contexto de negocio id_empresa=%s", request.config.id_empresa)
    except Exception as e:
        logger.warning("Error inesperado en contexto de negocio: %s", e)
    
    if contexto_negocio:
        logger.debug("Contexto de negocio cargado para id_empresa=%s", request.config.id_empresa)

    # 3. System prompt del orquestador CON memoria y contexto de negocio
    config_dict = request.config.model_dump()
    system_prompt = build_orquestador_system_prompt_with_memory(
        config_dict, memory, contexto_negocio=contexto_negocio
    )
    logger.debug("System prompt length: %s chars", len(system_prompt))

    # 4. Agente orquestador (OpenAI): system prompt + mensaje → respuesta (async nativo)
    reply, agent_to_invoke = await invoke_orquestador(system_prompt, request.message)

    logger.info(
        "Orquestador decidió",
        extra={"extra_fields": {"agent_to_invoke": agent_to_invoke, "reply_preview": reply[:200]}}
    )

    # Validar que agent_to_invoke coincida con la modalidad; corregir si el LLM se desvía
    agent_key = modalidad_to_agent(request.config.modalidad or "")
    if agent_to_invoke and agent_to_invoke != agent_key:
        logger.warning(
            "LLM devolvió agent distinto a modalidad; corregido",
            extra={"extra_fields": {
                "llm_agent": agent_to_invoke,
                "modalidad": request.config.modalidad,
                "agent_corregido": agent_key,
                "session_id": request.session_id,
            }}
        )
        app_metrics.llm_agent_corrections_total.labels(
            modalidad=(request.config.modalidad or "unknown"),
            llm_agent=agent_to_invoke,
        ).inc()
        agent_to_invoke = agent_key

    # 5. Si el orquestador detectó que debe delegar, llamar al agente MCP
    final_reply = reply
    agent_used = None
    action = "respond"

    if agent_to_invoke:
        logger.info("Delegando a agente MCP", extra={"extra_fields": {"agent": agent_to_invoke}})

        context = {
            "session_id": request.session_id,
            "config": request.config.model_dump(),
        }

        specialist_response = await invoke_mcp_agent(
            agent_name=agent_to_invoke,
            message=request.message,
            session_id=request.session_id,
            context=context
        )

        if specialist_response:
            logger.info(
                "Respuesta MCP recibida",
                extra={"extra_fields": {"agent": agent_to_invoke, "response_preview": specialist_response[:150]}}
            )
            final_reply = specialist_response
            agent_used = agent_to_invoke
            action = "delegate"
        else:
            logger.warning(
                "Error al invocar agente MCP, usando respuesta orquestador",
                extra={"extra_fields": {"agent": agent_to_invoke}}
            )
            final_reply = reply
            action = "respond"

    # 6. GUARDAR EN MEMORIA
    await memory_manager.add(
        session_id=request.session_id,
        user_message=request.message,
        agent_used=agent_used,
        response=final_reply
    )

    logger.info("Respuesta final", extra={"extra_fields": {"session_id": request.session_id, "action": action, "reply_preview": final_reply[:200]}})

    await app_metrics.record_request(time.perf_counter() - start_time, action, error=False)
    return ChatResponse(
        reply=final_reply,
        session_id=request.session_id,
        agent_used=agent_used,
        action=action
    )


@app.post("/api/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Endpoint principal que recibe POST desde n8n.
    
    Construye el system prompt (identidad, reglas), invoca el agente orquestador
    (OpenAI gpt-4o-mini / gpt-4o) y devuelve la respuesta.
    """
    start_time = time.perf_counter()
    
    # Validación de inputs
    if not request.message or not request.message.strip():
        await app_metrics.record_request(time.perf_counter() - start_time, "respond", error=True)
        raise HTTPException(
            status_code=400,
            detail="El campo 'message' no puede estar vacío"
        )

    if request.session_id is None or request.session_id < 0:
        await app_metrics.record_request(time.perf_counter() - start_time, "respond", error=True)
        raise HTTPException(
            status_code=400,
            detail="El campo 'session_id' debe ser un entero no negativo"
        )

    if not request.config.id_empresa or request.config.id_empresa <= 0:
        await app_metrics.record_request(time.perf_counter() - start_time, "respond", error=True)
        raise HTTPException(
            status_code=400,
            detail="El campo 'config.id_empresa' debe ser un número mayor a 0"
        )

    try:
        response = await asyncio.wait_for(
            _process_chat(request),
            timeout=app_config.CHAT_TIMEOUT
        )
        # Éxito - las métricas ya se registraron en _process_chat()
        return response
    except asyncio.TimeoutError:
        await app_metrics.record_request(time.perf_counter() - start_time, "timeout", error=True)
        logger.error(
            "Chat timeout (>%ss) session_id=%s",
            app_config.CHAT_TIMEOUT,
            request.session_id,
        )
        raise HTTPException(status_code=504, detail="El agente tardó demasiado en responder. Intenta de nuevo.")
    except asyncio.CancelledError:
        await app_metrics.record_request(time.perf_counter() - start_time, "cancelled", error=True)
        raise
    except ValueError as e:
        await app_metrics.record_request(time.perf_counter() - start_time, "respond", error=True)
        logger.error("Config/LLM error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        await app_metrics.record_request(time.perf_counter() - start_time, "respond", error=True)
        logger.exception("Error procesando request: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "orquestador"}


@app.get("/config")
async def config():
    """Devuelve URLs MCP, flags y modelo OpenAI (para verificar config)."""
    return {
        "mcp_reserva_url": app_config.MCP_RESERVA_URL,
        "mcp_cita_url": app_config.MCP_CITA_URL,
        "mcp_venta_url": app_config.MCP_VENTA_URL,
        "mcp_reserva_enabled": app_config.MCP_RESERVA_ENABLED,
        "openai_model": app_config.OPENAI_MODEL,
    }


@app.get("/memory/stats")
async def memory_stats():
    """Estadísticas de memoria (debug)"""
    return await memory_manager.get_stats()


@app.post("/memory/clear/{session_id}")
async def clear_memory(session_id: str):
    """Limpia la memoria de una sesión específica. session_id en URL viene como str; se convierte a int."""
    try:
        sid = int(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="session_id debe ser un número entero")
    await memory_manager.clear(sid)
    return {"message": f"Memoria limpiada para session_id: {sid}"}


@app.get("/metrics")
async def metrics():
    """
    Endpoint Prometheus. Devuelve métricas en formato text/plain.
    Puede ser scrapeado por Prometheus cada 60s para almacenar en su DB.
    """
    return Response(
        content=app_metrics.get_metrics_endpoint(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/")
async def root():
    """Root endpoint - Información del servicio"""
    return {
        "service": "MaravIA Orquestador",
        "version": app_config.VERSION,
        "status": "running",
        "features": [
            "Detección de intención con structured output",
            "Memoria conversacional (últimos 10 turnos)",
            "Delegación a agentes MCP"
        ],
        "endpoints": {
            "chat": "/api/agent/chat",
            "config": "/config",
            "health": "/health",
            "metrics": "/metrics",
            "memory_stats": "/memory/stats",
            "clear_memory": "/memory/clear/{session_id}",
            "docs": "/docs",
            "redoc": "/redoc"
        },
        "info": "Visita /docs para ver la documentación interactiva y probar los endpoints"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.orquestador.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
