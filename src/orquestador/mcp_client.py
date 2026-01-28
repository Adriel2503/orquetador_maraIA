"""
Cliente MCP para consumir agentes especializados (Venta, Cita, Reserva).
Incluye circuit breaker y retry con backoff exponencial.
"""

import asyncio
import time
from enum import Enum
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


class CircuitState(Enum):
    """Estados del circuit breaker"""
    CLOSED = "closed"  # Funcionando normalmente
    OPEN = "open"  # Fallando, rechazando requests
    HALF_OPEN = "half_open"  # Probando si se recuperó


class CircuitBreaker:
    """Circuit breaker simple para proteger llamadas MCP"""
    
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitState.CLOSED
    
    def record_success(self):
        """Registra un éxito y resetea el contador"""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = None
    
    def record_failure(self):
        """Registra un fallo y actualiza el estado"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            print(f"[CIRCUIT_BREAKER] Circuit abierto después de {self.failure_count} fallos")
    
    def can_attempt(self) -> bool:
        """Verifica si se puede intentar una llamada"""
        if self.state == CircuitState.CLOSED:
            return True
        
        if self.state == CircuitState.OPEN:
            # Verificar si ha pasado el tiempo de reset
            if self.last_failure_time and (time.time() - self.last_failure_time) >= self.reset_timeout:
                self.state = CircuitState.HALF_OPEN
                print(f"[CIRCUIT_BREAKER] Circuit en estado HALF_OPEN, probando recuperación")
                return True
            return False
        
        # HALF_OPEN: permitir un intento
        return True
    
    def get_state(self) -> str:
        """Retorna el estado actual como string"""
        return self.state.value


# Circuit breakers por agente
_circuit_breakers: Dict[str, CircuitBreaker] = {}


def _get_circuit_breaker(agent_name: str) -> CircuitBreaker:
    """Obtiene o crea el circuit breaker para un agente"""
    if agent_name not in _circuit_breakers:
        _circuit_breakers[agent_name] = CircuitBreaker(
            failure_threshold=app_config.MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            reset_timeout=app_config.MCP_CIRCUIT_BREAKER_RESET_TIMEOUT
        )
    return _circuit_breakers[agent_name]


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


async def _invoke_mcp_agent_internal(agent_name: str, message: str, session_id: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Invocación interna del agente MCP sin circuit breaker ni retry.
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
    
    # Cargar tools usando API oficial de MCP (client.get_tools) con timeout
    print(f"[MCP] Cargando tools del agente {agent_name}...")
    tools = await asyncio.wait_for(
        client.get_tools(),
        timeout=app_config.MCP_TIMEOUT
    )
    
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
        # Invocar el tool "chat" con los argumentos correctos y timeout
        # El tool "chat" del agente espera: message, session_id, context
        if isinstance(chat_tool, StructuredTool):
            result = await asyncio.wait_for(
                chat_tool.ainvoke({
                    "message": message,
                    "session_id": session_id,
                    "context": context or {}
                }),
                timeout=app_config.MCP_TIMEOUT
            )
        else:
            # Fallback: intentar con dict de argumentos
            result = await asyncio.wait_for(
                chat_tool.ainvoke({
                    "message": message,
                    "session_id": session_id,
                    "context": context or {}
                }),
                timeout=app_config.MCP_TIMEOUT
            )
        return str(result)
    
    # Si no hay tool de chat, retornar información sobre tools disponibles
    tools_info = ", ".join([tool.name for tool in tools[:5]])
    print(f"[MCP] No se encontró tool 'chat'. Tools disponibles: {tools_info}")
    return f"[MCP {agent_name}] Agente disponible pero sin tool 'chat'. Tools: {tools_info}"


async def invoke_mcp_agent(agent_name: str, message: str, session_id: str, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Invoca un agente MCP especializado con circuit breaker y retry con backoff exponencial.
    
    Args:
        agent_name: Nombre del agente ("venta", "cita", "reserva")
        message: Mensaje del cliente
        session_id: ID de sesión para contexto
        context: Contexto adicional (config del bot, etc.)
    
    Returns:
        Respuesta del agente MCP o None si hay error
    """
    circuit_breaker = _get_circuit_breaker(agent_name)
    
    # Verificar circuit breaker
    if not circuit_breaker.can_attempt():
        print(f"[CIRCUIT_BREAKER] Circuit abierto para {agent_name}, rechazando request")
        return None
    
    # Retry con backoff exponencial
    max_retries = app_config.MCP_MAX_RETRIES
    last_error = None
    
    for attempt in range(max_retries):
        try:
            result = await _invoke_mcp_agent_internal(agent_name, message, session_id, context)
            
            if result is not None:
                # Éxito: registrar en circuit breaker
                circuit_breaker.record_success()
                if attempt > 0:
                    print(f"[MCP] Éxito después de {attempt + 1} intentos")
                return result
            else:
                # Resultado None se considera fallo
                last_error = "Respuesta None del agente"
                circuit_breaker.record_failure()
                
        except asyncio.TimeoutError:
            last_error = f"Timeout (>{app_config.MCP_TIMEOUT}s)"
            circuit_breaker.record_failure()
            print(f"[MCP] Timeout en intento {attempt + 1}/{max_retries}")
            
        except Exception as e:
            last_error = str(e)
            circuit_breaker.record_failure()
            print(f"[MCP] Error en intento {attempt + 1}/{max_retries}: {e}")
        
        # Si no es el último intento, esperar con backoff exponencial
        if attempt < max_retries - 1:
            backoff_time = 2 ** attempt  # 1s, 2s, 4s
            print(f"[MCP] Esperando {backoff_time}s antes de reintentar...")
            await asyncio.sleep(backoff_time)
    
    # Todos los intentos fallaron
    print(f"[MCP] Todos los intentos fallaron para {agent_name}. Último error: {last_error}")
    print(f"[CIRCUIT_BREAKER] Estado actual: {circuit_breaker.get_state()}, Fallos: {circuit_breaker.failure_count}")
    return None

