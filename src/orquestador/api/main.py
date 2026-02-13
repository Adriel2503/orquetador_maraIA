"""FastAPI app principal del orquestador"""

import asyncio
import json as _json_mod
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

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


def _fetch_contexto_negocio_sync(id_empresa: int) -> Optional[str]:
    """Llama al endpoint para obtener contexto de negocio (sync, para ejecutar en thread)."""
    url = app_config.CONTEXTO_NEGOCIO_ENDPOINT
    body = _json_mod.dumps({"codOpe": "OBTENER_CONTEXTO_NEGOCIO", "id_empresa": id_empresa}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=app_config.CONTEXTO_NEGOCIO_TIMEOUT) as resp:
            data = _json_mod.loads(resp.read().decode())
            if data.get("success") and data.get("contexto_negocio"):
                return data["contexto_negocio"]
    except Exception as e:
        logger.debug("No se pudo obtener contexto de negocio: %s", e)
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
    
    start_time = time.perf_counter()
    try:
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
        
        app_metrics.record_request(time.perf_counter() - start_time, action, error=False)
        return ChatResponse(
            reply=final_reply,
            session_id=request.session_id,
            agent_used=agent_used,
            action=action
        )
    
    except ValueError as e:
        logger.error("Config/LLM error: %s", e)
        app_metrics.record_request(time.perf_counter() - start_time, "respond", error=True)
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error procesando request: %s", e)
        app_metrics.record_request(time.perf_counter() - start_time, "respond", error=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "orquestador"}


@app.get("/config")
async def config():
    """Devuelve configuración del orquestador (modo, URLs MCP, modelo OpenAI)."""
    config_data = {
        "agent_mode": app_config.AGENT_MODE,
        "openai_model": app_config.OPENAI_MODEL,
    }

    # Agregar info de MCP solo si está en modo MCP
    if app_config.AGENT_MODE == "mcp":
        config_data.update({
            "mcp_reserva_url": app_config.MCP_RESERVA_URL,
            "mcp_cita_url": app_config.MCP_CITA_URL,
            "mcp_venta_url": app_config.MCP_VENTA_URL,
            "mcp_reserva_enabled": app_config.MCP_RESERVA_ENABLED,
        })

    # Agregar info de agentes disponibles en modo local
    if app_config.AGENT_MODE == "local":
        try:
            from ..integrations.agent_invoker import get_available_agents
        except ImportError:
            from orquestador.integrations.agent_invoker import get_available_agents
        config_data["agents_available"] = get_available_agents()
        config_data["agent_paths"] = app_config._AGENT_PATHS

    return config_data


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
    """Métricas in-memory: requests, errores, latencia, estado circuit breakers (JSON)."""
    cb_states = await get_circuit_breaker_states()
    return app_metrics.get_metrics_with_circuit_breakers(cb_states)


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
