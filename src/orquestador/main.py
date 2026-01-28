"""FastAPI app principal del orquestador"""

import asyncio
import sys
import time
from pathlib import Path

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
    from .models import ChatRequest, ChatResponse
    from . import config as app_config
    from .prompts import build_orquestador_system_prompt_with_memory
    from .llm import invoke_orquestador
    from .mcp_client import invoke_mcp_agent, get_circuit_breaker_states
    from .memory import memory_manager
    from .logging_config import get_logger
    from . import metrics as app_metrics
except ImportError:
    from models import ChatRequest, ChatResponse
    import config as app_config
    from prompts import build_orquestador_system_prompt_with_memory
    from llm import invoke_orquestador
    from mcp_client import invoke_mcp_agent, get_circuit_breaker_states
    from memory import memory_manager
    from logging_config import get_logger
    import metrics as app_metrics

logger = get_logger("main")

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
    
    if not request.session_id or not request.session_id.strip():
        raise HTTPException(
            status_code=400,
            detail="El campo 'session_id' no puede estar vacío"
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
        
        # 2. System prompt del orquestador CON memoria
        config_dict = request.config.model_dump()
        system_prompt = build_orquestador_system_prompt_with_memory(config_dict, memory)
        logger.debug("System prompt length: %s chars", len(system_prompt))
        
        # 3. Agente orquestador (OpenAI): system prompt + mensaje → respuesta (async nativo)
        reply, agent_to_invoke = await invoke_orquestador(system_prompt, request.message)
        
        logger.info(
            "Orquestador decidió",
            extra={"extra_fields": {"agent_to_invoke": agent_to_invoke, "reply_preview": reply[:200]}}
        )
        
        # 4. Si el orquestador detectó que debe delegar, llamar al agente MCP
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
        
        # 5. GUARDAR EN MEMORIA
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
    """Limpia la memoria de una sesión específica"""
    await memory_manager.clear(session_id)
    return {"message": f"Memoria limpiada para session_id: {session_id}"}


@app.get("/metrics")
async def metrics():
    """Métricas in-memory: requests, errores, latencia, estado circuit breakers (JSON)."""
    return app_metrics.get_metrics_with_circuit_breakers(get_circuit_breaker_states())


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
    
    # Si se ejecuta directamente, usar string de importación para que reload funcione
    # Si se ejecuta como módulo, usar la ruta del módulo completa
    if Path(__file__).parent.name == "orquestador" and Path(__file__).parent.parent.name == "src":
        # Ejecutado directamente desde src/orquestador/
        # Usar "main:app" porque ya agregamos el directorio al sys.path
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=True
        )
    else:
        # Ejecutado como módulo desde la raíz
        uvicorn.run(
            "src.orquestador.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True
        )
