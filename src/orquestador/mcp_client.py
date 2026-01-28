"""
Cliente MCP para consumir agentes especializados (Venta, Cita, Reserva).
"""

from typing import Optional, Dict, Any

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from langchain_core.tools import StructuredTool
    MCP_AVAILABLE = True
except ImportError:
    MultiServerMCPClient = None
    MCP_AVAILABLE = False

try:
    from . import config as app_config
except ImportError:
    import config as app_config

_mcp_client: Optional[MultiServerMCPClient] = None


def _get_mcp_client() -> Optional[MultiServerMCPClient]:
    """Lazy init del cliente MCP."""
    global _mcp_client
    
    if not MCP_AVAILABLE:
        print("[MCP] langchain-mcp-adapters no está instalado. Instala con: pip install langchain-mcp-adapters")
        return None
    
    if _mcp_client is None:
        servers: Dict[str, Dict[str, str]] = {}
        
        # Solo Reserva está activo por ahora
        if app_config.MCP_RESERVA_ENABLED and app_config.MCP_RESERVA_URL:
            servers["reserva"] = {
                "transport": "http",
                "url": app_config.MCP_RESERVA_URL
            }
        
        # Venta y Cita se activarán más adelante
        # if app_config.MCP_VENTA_URL:
        #     servers["venta"] = {"transport": "http", "url": app_config.MCP_VENTA_URL}
        # if app_config.MCP_CITA_URL:
        #     servers["cita"] = {"transport": "http", "url": app_config.MCP_CITA_URL}
        
        if not servers:
            print("[MCP] No hay servidores MCP configurados")
            return None
        
        try:
            _mcp_client = MultiServerMCPClient(servers)
            print(f"[MCP] Cliente inicializado con servidores: {list(servers.keys())}")
        except Exception as e:
            print(f"[MCP] Error inicializando cliente: {e}")
            return None
    
    return _mcp_client


async def invoke_mcp_agent(agent_name: str, message: str, session_id: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Invoca un agente MCP especializado.
    
    Args:
        agent_name: Nombre del agente ("venta", "cita", "reserva")
        message: Mensaje del cliente
        session_id: ID de sesión para contexto
        context: Contexto adicional (config del bot, etc.)
    
    Returns:
        Respuesta del agente MCP o None si hay error
    """
    client = _get_mcp_client()
    if client is None:
        return None
    
    if agent_name not in ["venta", "cita", "reserva"]:
        print(f"[MCP] Agente desconocido: {agent_name}")
        return None
    
    if agent_name != "reserva":
        print(f"[MCP] Agente {agent_name} no disponible aún. Solo Reserva está activo.")
        return None
    
    try:
        # Cargar tools usando API oficial de MCP (client.get_tools)
        print(f"[MCP] Cargando tools del agente {agent_name}...")
        tools = await client.get_tools()
        
        if not tools:
            print(f"[MCP] No se encontraron tools para el agente {agent_name}")
            return None
        
        print(f"[MCP] Tools disponibles: {[tool.name for tool in tools]}")
        
        # Buscar el tool "chat" que es el principal
        chat_tool = None
        for tool in tools:
            if tool.name.lower() in ["chat", "process_message", "handle_message", "respond"]:
                chat_tool = tool
                break
        
        if chat_tool:
            print(f"[MCP] Usando tool: {chat_tool.name}")
            try:
                # Invocar el tool "chat" con los argumentos correctos
                # El tool "chat" del agente espera: message, session_id, context
                if isinstance(chat_tool, StructuredTool):
                    result = await chat_tool.ainvoke({
                        "message": message,
                        "session_id": session_id,
                        "context": context or {}
                    })
                else:
                    # Fallback: intentar con dict de argumentos
                    result = await chat_tool.ainvoke({
                        "message": message,
                        "session_id": session_id,
                        "context": context or {}
                    })
                return str(result)
            except Exception as e:
                print(f"[MCP] Error invocando tool {chat_tool.name}: {e}")
                import traceback
                traceback.print_exc()
                return None
        
        # Si no hay tool de chat, retornar información sobre tools disponibles
        tools_info = ", ".join([tool.name for tool in tools[:5]])
        print(f"[MCP] No se encontró tool 'chat'. Tools disponibles: {tools_info}")
        return f"[MCP {agent_name}] Agente disponible pero sin tool 'chat'. Tools: {tools_info}"
        
    except Exception as e:
        print(f"[MCP] Error invocando agente {agent_name}: {e}")
        import traceback
        traceback.print_exc()
        return None


