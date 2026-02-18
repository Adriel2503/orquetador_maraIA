"""FastAPI app principal del orquestador"""

import asyncio
import json as _json_mod
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timedelta

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
import json

# Importación que funciona tanto como módulo como script directo
try:
    from ..config.models import ChatRequest, ChatResponse
    from ..config import config as app_config
    from ..prompts import build_orquestador_system_prompt_with_memory
    from ..integrations.llm import invoke_orquestador
    from ..integrations.mcp_client import invoke_mcp_agent, get_circuit_breaker_states
    from ..services.memory import memory_manager
    from ..infrastructure.logging_config import get_logger
    from ..infrastructure import metrics as app_metrics
except ImportError:
    from orquestador.config.models import ChatRequest, ChatResponse
    from orquestador.config import config as app_config
    from orquestador.prompts import build_orquestador_system_prompt_with_memory
    from orquestador.integrations.llm import invoke_orquestador
    from orquestador.integrations.mcp_client import invoke_mcp_agent, get_circuit_breaker_states
    from orquestador.services.memory import memory_manager
    from orquestador.infrastructure.logging_config import get_logger
    from orquestador.infrastructure import metrics as app_metrics

logger = get_logger("main")

# Cache simple + circuit breaker para contexto de negocio
_contexto_cache: Dict[int, tuple[str, datetime]] = {}  # id_empresa -> (contexto, timestamp)
_contexto_cache_ttl = 3600  # 1 hora
_contexto_failures: Dict[int, tuple[int, datetime]] = {}  # id_empresa -> (failure_count, last_failure_time)
_contexto_failure_threshold = 3
_contexto_failure_reset = 300  # 5 minutos


def _is_contexto_circuit_open(id_empresa: int) -> bool:
    """Verifica si el circuit breaker para contexto está abierto."""
    if id_empresa not in _contexto_failures:
        return False
    failure_count, last_failure_time = _contexto_failures[id_empresa]
    if failure_count >= _contexto_failure_threshold:
        # Verificar si expiró el reset timeout
        if (datetime.now() - last_failure_time).total_seconds() < _contexto_failure_reset:
            return True
        # Expiró, resetear
        del _contexto_failures[id_empresa]
        return False
    return False


def _fetch_contexto_negocio_sync(id_empresa: int) -> Optional[str]:
    """
    Obtiene contexto de negocio con cache + circuit breaker + retry con backoff.
    Llama al endpoint para obtener contexto de negocio (sync, para ejecutar en thread).
    """
    global _contexto_cache, _contexto_failures

    # 1. Verificar cache
    if id_empresa in _contexto_cache:
        contexto, timestamp = _contexto_cache[id_empresa]
        if (datetime.now() - timestamp).total_seconds() < _contexto_cache_ttl:
            logger.debug("Contexto desde cache para id_empresa=%s", id_empresa)
            return contexto

    # 2. Verificar circuit breaker
    if _is_contexto_circuit_open(id_empresa):
        logger.warning("Circuit abierto para contexto de negocio id_empresa=%s", id_empresa)
        return None

    # 3. Retry con backoff exponencial (hasta 2 intentos)
    max_retries = 2
    last_error = None
    
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
                if data.get("success") and data.get("contexto_negocio"):
                    contexto = data["contexto_negocio"]
                    # Guardar en cache
                    _contexto_cache[id_empresa] = (contexto, datetime.now())
                    # Reset failures si era éxito
                    if id_empresa in _contexto_failures:
                        del _contexto_failures[id_empresa]
                    return contexto
        except Exception as e:
            last_error = e
            logger.debug(
                "Error obteniendo contexto intento %d/%d id_empresa=%s: %s",
                attempt + 1, max_retries, id_empresa, e
            )
            # Retry con backoff: 1s, 2s
            if attempt < max_retries - 1:
                backoff = 2 ** attempt
                time.sleep(backoff)
    
    # Todos los intentos fallaron
    logger.debug("Todos los intentos fallaron para contexto id_empresa=%s", id_empresa)
    # Registrar fallo en circuit breaker
    if id_empresa not in _contexto_failures:
        _contexto_failures[id_empresa] = (0, datetime.now())
    failure_count, _ = _contexto_failures[id_empresa]
    _contexto_failures[id_empresa] = (failure_count + 1, datetime.now())
    
    return None


app = FastAPI(
    title="MaravIA Orquestador",
    description="Orquestador que enruta conversaciones a agentes especializados MCP (Venta, Cita, Reserva)",
    version=app_config.VERSION
)

# CORS - ajustar según necesidad
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especificar dominios permitidos
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
    logger.debug("Request body: %s", json.dumps(request_dict, ensure_ascii=False))

    # 1. CARGAR MEMORIA (historial de conversación)
    memory = await memory_manager.get(request.session_id, limit=10)
    logger.info("Memoria cargada", extra={"extra_fields": {"session_id": request.session_id, "turnos": len(memory)}})
    current_agent = None
    if memory:
        current_agent = await memory_manager.get_current_agent(request.session_id)
        if current_agent:
            logger.info("Agente activo en sesión", extra={"extra_fields": {"session_id": request.session_id, "agent": current_agent}})

    # 2. Obtener contexto de negocio (para responder preguntas básicas sin delegar)
    contexto_negocio = await asyncio.to_thread(
        _fetch_contexto_negocio_sync, request.config.id_empresa
    )
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
    # Validación de inputs
    if not request.message or not request.message.strip():
        raise HTTPException(
            status_code=400,
            detail="El campo 'message' no puede estar vacío"
        )

    if request.session_id is None or request.session_id < 0:
        raise HTTPException(
            status_code=400,
            detail="El campo 'session_id' debe ser un entero no negativo"
        )

    if not request.config.id_empresa or request.config.id_empresa <= 0:
        raise HTTPException(
            status_code=400,
            detail="El campo 'config.id_empresa' debe ser un número mayor a 0"
        )

    try:
        return await asyncio.wait_for(
            _process_chat(request),
            timeout=app_config.CHAT_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.error(
            "Chat timeout (>%ss) session_id=%s",
            app_config.CHAT_TIMEOUT,
            request.session_id,
        )
        raise HTTPException(status_code=504, detail="El agente tardó demasiado en responder. Intenta de nuevo.")
    except asyncio.CancelledError:
        raise
    except ValueError as e:
        logger.error("Config/LLM error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
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
    return app_metrics.get_metrics_endpoint()


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
