"""FastAPI app principal del orquestador"""

import asyncio
import sys
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
    from .mcp_client import invoke_mcp_agent
    from .memory import memory_manager
except ImportError:
    from models import ChatRequest, ChatResponse
    import config as app_config
    from prompts import build_orquestador_system_prompt_with_memory
    from llm import invoke_orquestador
    from mcp_client import invoke_mcp_agent
    from memory import memory_manager

app = FastAPI(
    title="MaravIA Orquestador",
    description="Orquestador que enruta conversaciones a agentes especializados MCP (Venta, Cita, Reserva)",
    version="0.1.0"
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
    try:
        # Log completo para debugging - muestra todo el JSON recibido
        print(f"\n{'='*60}")
        print(f" POST /api/agent/chat - REQUEST RECIBIDO")
        print(f"{'='*60}")
        print(f" Mensaje: {request.message}")
        print(f" Session ID: {request.session_id}")
        print(f"\n CONFIGURACIÓN DEL BOT:")
        print(f"   - Nombre: {request.config.nombre_bot}")
        print(f"   - ID Empresa: {request.config.id_empresa}")
        print(f"   - Tipo: {request.config.tipo_bot}")
        print(f"   - Objetivo: {request.config.objetivo_principal}")
        print(f"   - Rol: {request.config.rol_bot}")
        print(f"\n MCP (solo Reserva activo):")
        print(f"   - Reserva URL: {app_config.MCP_RESERVA_URL}")
        print(f"   - Reserva habilitado: {app_config.MCP_RESERVA_ENABLED}")
        print(f"\n LLM:")
        print(f"   - Modelo: {app_config.OPENAI_MODEL}")
        
        # Mostrar JSON completo en formato legible
        request_dict = request.model_dump()
        print(f"\n JSON COMPLETO RECIBIDO:")
        print(json.dumps(request_dict, indent=2, ensure_ascii=False))
        print(f"{'='*60}\n")
        
        # 1. CARGAR MEMORIA (historial de conversación)
        memory = memory_manager.get(request.session_id, limit=10)
        print(f"[ORQUESTADOR] Memoria cargada: {len(memory)} turnos previos")
        if memory:
            current_agent = memory_manager.get_current_agent(request.session_id)
            print(f"[ORQUESTADOR] Agente activo: {current_agent}")
        
        # 2. System prompt del orquestador CON memoria
        config_dict = request.config.model_dump()
        system_prompt = build_orquestador_system_prompt_with_memory(config_dict, memory)
        print(f"[ORQUESTADOR] System prompt length: {len(system_prompt)} chars")
        
        # 3. Agente orquestador (OpenAI): system prompt + mensaje → respuesta (en thread para no bloquear)
        reply, agent_to_invoke = await asyncio.to_thread(invoke_orquestador, system_prompt, request.message)
        
        print(f"[ORQUESTADOR] Respuesta: {reply[:200]}...")
        print(f"[ORQUESTADOR] Agente a invocar: {agent_to_invoke}")
        
        # 4. Si el orquestador detectó que debe delegar, llamar al agente MCP
        final_reply = reply
        agent_used = None
        action = "respond"
        
        if agent_to_invoke:
            print(f"[MCP] Delegando a agente: {agent_to_invoke}")
            
            # Preparar contexto para el agente MCP
            context = {
                "session_id": request.session_id,
                "config": request.config.model_dump(),
            }
            
            # ESPERAR respuesta del agente especializado
            specialist_response = await invoke_mcp_agent(
                agent_name=agent_to_invoke,
                message=request.message,
                session_id=request.session_id,
                context=context
            )
            
            if specialist_response:
                print(f"[MCP] Respuesta recibida del agente {agent_to_invoke}")
                print(f"[MCP] Respuesta final: {specialist_response[:150]}...")
                
                # Usar respuesta del agente especializado directamente (ya tiene personalidad)
                final_reply = specialist_response
                agent_used = agent_to_invoke
                action = "delegate"
            else:
                print(f"[MCP] Error al invocar agente {agent_to_invoke}, usando respuesta del orquestador")
                # Si falla MCP, usar la respuesta del orquestador
                final_reply = reply
                action = "respond"
        
        # 5. GUARDAR EN MEMORIA
        memory_manager.add(
            session_id=request.session_id,
            user_message=request.message,
            agent_used=agent_used,
            response=final_reply
        )
        
        print(f"[ORQUESTADOR] Respuesta final: {final_reply[:200]}...")
        
        return ChatResponse(
            reply=final_reply,
            session_id=request.session_id,
            agent_used=agent_used,
            action=action
        )
    
    except ValueError as e:
        print(f"Config/LLM error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"Error procesando request: {str(e)}")
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
    return memory_manager.get_stats()


@app.post("/memory/clear/{session_id}")
async def clear_memory(session_id: str):
    """Limpia la memoria de una sesión específica"""
    memory_manager.clear(session_id)
    return {"message": f"Memoria limpiada para session_id: {session_id}"}


@app.get("/")
async def root():
    """Root endpoint - Información del servicio"""
    return {
        "service": "MaravIA Orquestador",
        "version": "0.2.0",
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
