"""
Cliente MCP para consumir agentes especializados (Venta, Cita, Reserva).
Incluye circuit breaker y retry con backoff exponencial.
"""

import ast
import asyncio
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Union

try:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    MCP_AVAILABLE = True
except ImportError:
    MultiServerMCPClient = None
    MCP_AVAILABLE = False

try:
    from ..config import config as app_config
    from ..infrastructure.logging_config import get_logger
except ImportError:
    from orquestador.config import config as app_config
    from orquestador.infrastructure.logging_config import get_logger

logger = get_logger("mcp_client")
_mcp_client: Optional[MultiServerMCPClient] = None
_mcp_client_lock = asyncio.Lock()

# Cache de tools: se carga una sola vez en el primer uso.
# Las tools de los agentes MCP no cambian en tiempo de ejecución.
_tools_cache: Optional[List] = None
_tools_cache_lock = asyncio.Lock()


class CircuitState(Enum):
    """Estados del circuit breaker"""
    CLOSED = "closed"  # Funcionando normalmente
    OPEN = "open"  # Fallando, rechazando requests
    HALF_OPEN = "half_open"  # Probando si se recuperó


class CircuitBreaker:
    """Circuit breaker para proteger llamadas MCP. Thread-safe para concurrencia async."""

    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = CircuitState.CLOSED
        self._lock = asyncio.Lock()

    async def record_success(self) -> None:
        """Registra un éxito y resetea el contador. Protegido con lock para evitar race conditions."""
        async with self._lock:
            self.failure_count = 0
            self.state = CircuitState.CLOSED
            self.last_failure_time = None

    async def record_failure(self) -> None:
        """Registra un fallo y actualiza el estado. Protegido con lock para evitar race conditions."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning("Circuit abierto después de %s fallos", self.failure_count)

    async def can_attempt(self) -> bool:
        """
        Verifica si se puede intentar una llamada.

        CLOSED: siempre permite.
        OPEN: permite solo si expiró el reset_timeout, transitando a HALF_OPEN bajo lock
              para garantizar que una sola coroutine realice esa transición.
        HALF_OPEN: permite exactamente un intento a la vez; las demás coroutines ven
                   el estado como OPEN (bloqueado) hasta que el intento confirme éxito
                   (record_success → CLOSED) o falle (record_failure → OPEN).
        """
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self.last_failure_time and (time.time() - self.last_failure_time) >= self.reset_timeout:
                async with self._lock:
                    # Double-check: otra coroutine pudo haber transitado ya
                    if self.state == CircuitState.OPEN:
                        self.state = CircuitState.HALF_OPEN
                        logger.info("Circuit en estado HALF_OPEN, probando recuperación")
                return True
            return False

        # HALF_OPEN: solo 1 intento a la vez; bloqueamos el estado para las demás
        async with self._lock:
            if self.state != CircuitState.HALF_OPEN:
                return self.state == CircuitState.CLOSED
            self.state = CircuitState.OPEN  # las demás coroutines verán OPEN hasta confirmar éxito
        return True

    def get_state(self) -> str:
        """Retorna el estado actual como string."""
        return self.state.value


# Circuit breakers por agente (protegidos con lock para concurrencia async)
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_circuit_breakers_lock = asyncio.Lock()


async def _get_circuit_breaker(agent_name: str) -> CircuitBreaker:
    """Obtiene o crea el circuit breaker para un agente. Thread-safe para concurrencia async."""
    async with _circuit_breakers_lock:
        if agent_name not in _circuit_breakers:
            _circuit_breakers[agent_name] = CircuitBreaker(
                failure_threshold=app_config.MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD,
                reset_timeout=app_config.MCP_CIRCUIT_BREAKER_RESET_TIMEOUT
            )
        return _circuit_breakers[agent_name]


async def get_circuit_breaker_states() -> Dict[str, Dict[str, Any]]:
    """Devuelve el estado de todos los circuit breakers (para /metrics). Lectura bajo lock."""
    async with _circuit_breakers_lock:
        return {
            name: {"state": cb.get_state(), "failure_count": cb.failure_count}
            for name, cb in _circuit_breakers.items()
        }


async def _get_mcp_client() -> Optional[MultiServerMCPClient]:
    """
    Lazy init del cliente MCP. Thread-safe para concurrencia async.
    Usa double-checked locking para garantizar una única instancia por proceso.
    """
    global _mcp_client

    if not MCP_AVAILABLE:
        logger.warning("langchain-mcp-adapters no está instalado. Instala con: pip install langchain-mcp-adapters")
        return None

    # Fast path: si ya existe, devolver sin tomar el lock (caso habitual)
    if _mcp_client is not None:
        return _mcp_client

    async with _mcp_client_lock:
        # Double-check: otra corutina pudo haberlo creado mientras esperábamos el lock
        if _mcp_client is not None:
            return _mcp_client

        servers: Dict[str, Dict[str, str]] = {}

        if app_config.MCP_RESERVA_ENABLED and app_config.MCP_RESERVA_URL:
            servers["reserva"] = {
                "transport": "http",
                "url": app_config.MCP_RESERVA_URL
            }

        if app_config.MCP_CITA_ENABLED and app_config.MCP_CITA_URL:
            servers["cita"] = {
                "transport": "http",
                "url": app_config.MCP_CITA_URL
            }

        if app_config.MCP_VENTA_ENABLED and app_config.MCP_VENTA_URL:
            servers["venta"] = {
                "transport": "http",
                "url": app_config.MCP_VENTA_URL
            }

        if not servers:
            logger.warning("No hay servidores MCP configurados")
            return None

        try:
            _mcp_client = MultiServerMCPClient(servers)
            logger.info("Cliente MCP inicializado con servidores: %s", list(servers.keys()))
        except Exception as e:
            logger.exception("Error inicializando cliente MCP: %s", e)
            return None

    return _mcp_client


async def _get_cached_tools() -> Optional[List]:
    """
    Retorna la lista de tools MCP, cargándola una sola vez y cacheándola para
    todas las invocaciones siguientes. Las tools no cambian en tiempo de ejecución.

    Usa double-checked locking para evitar múltiples llamadas concurrentes al
    primer uso y garantizar que el cache se inicialice exactamente una vez.
    """
    global _tools_cache

    # Fast path: ya cacheadas (caso habitual tras la primera carga)
    if _tools_cache is not None:
        return _tools_cache

    async with _tools_cache_lock:
        # Double-check: otra coroutine pudo haberlas cargado mientras esperábamos
        if _tools_cache is not None:
            return _tools_cache

        client = await _get_mcp_client()
        if client is None:
            return None

        try:
            tools = await asyncio.wait_for(
                client.get_tools(),
                timeout=app_config.MCP_TIMEOUT
            )
            if tools:
                _tools_cache = tools
                logger.info(
                    "Tools MCP cacheadas (%d tools): %s",
                    len(tools), [t.name for t in tools]
                )
            return tools
        except asyncio.TimeoutError:
            logger.error("Timeout cargando tools MCP (>%ss)", app_config.MCP_TIMEOUT)
            return None
        except Exception as e:
            logger.exception("Error cargando tools MCP: %s", e)
            return None


def _extract_plain_text_from_agent_result(result: Any) -> str:
    """
    Extrae texto plano del resultado del agente MCP.
    El adaptador puede devolver: str, lista de bloques [{"type": "text", "text": "..."}],
    o un objeto con .content. Normalizamos siempre a un string para reply.
    """
    if result is None:
        return ""
    if isinstance(result, str):
        s = result.strip()
        # Si el adaptador devolvió la lista ya stringificada, intentar extraer texto
        if s.startswith("[") and ("'text'" in s or '"text"' in s):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, list):
                    return _extract_plain_text_from_agent_result(parsed) or s
            except (ValueError, SyntaxError):
                pass
        return s
    if isinstance(result, list):
        parts: List[str] = []
        for item in result:
            if isinstance(item, dict):
                if "text" in item and item["text"]:
                    parts.append(str(item["text"]).strip())
                elif "content" in item and item["content"]:
                    parts.append(str(item["content"]).strip())
            elif hasattr(item, "text"):
                parts.append(str(getattr(item, "text", "")).strip())
            elif hasattr(item, "content"):
                parts.append(str(getattr(item, "content", "")).strip())
        if parts:
            return "\n".join(p for p in parts if p)
    if isinstance(result, dict):
        if "text" in result and result["text"]:
            return str(result["text"]).strip()
        if "content" in result and result["content"]:
            return str(result["content"]).strip()
    if hasattr(result, "content"):
        content = getattr(result, "content", None)
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            return _extract_plain_text_from_agent_result(content)
    return str(result).strip()


async def _invoke_mcp_agent_internal(agent_name: str, message: str, session_id: int, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Invocación interna del agente MCP sin circuit breaker ni retry.
    """
    if agent_name not in ["venta", "cita", "reserva"]:
        logger.warning("Agente desconocido: %s", agent_name)
        return None

    # Verificar que el agente esté habilitado antes de cargar tools
    if agent_name == "reserva" and not (app_config.MCP_RESERVA_ENABLED and app_config.MCP_RESERVA_URL):
        logger.info("Agente reserva no configurado o deshabilitado.")
        return None
    if agent_name == "cita" and not (app_config.MCP_CITA_ENABLED and app_config.MCP_CITA_URL):
        logger.info("Agente cita no configurado o deshabilitado.")
        return None
    if agent_name == "venta" and not (app_config.MCP_VENTA_ENABLED and app_config.MCP_VENTA_URL):
        logger.info("Agente venta no configurado o deshabilitado.")
        return None

    # Tools cacheadas: se cargan una sola vez y se reutilizan en cada invocación
    tools = await _get_cached_tools()

    if not tools:
        logger.warning("No se encontraron tools para el agente %s", agent_name)
        return None

    logger.debug("Tools disponibles (desde cache): %s", [tool.name for tool in tools])
    
    # Buscar el tool "chat" que es el principal
    chat_tool = None
    for tool in tools:
        if tool.name.lower() in ["chat", "process_message", "handle_message", "respond"]:
            chat_tool = tool
            break
    
    if chat_tool:
        logger.debug("Usando tool: %s", chat_tool.name)
        result = await asyncio.wait_for(
            chat_tool.ainvoke({
                "message": message,
                "session_id": session_id,
                "context": context or {}
            }),
            timeout=app_config.MCP_TIMEOUT
        )
        text = _extract_plain_text_from_agent_result(result)
        return text if text else None
    
    tools_info = ", ".join([tool.name for tool in tools[:5]])
    logger.warning("No se encontró tool 'chat'. Tools disponibles: %s", tools_info)
    return f"[MCP {agent_name}] Agente disponible pero sin tool 'chat'. Tools: {tools_info}"


async def invoke_mcp_agent(agent_name: str, message: str, session_id: int, context: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Invoca un agente MCP especializado con circuit breaker y retry con backoff exponencial.
    
    Args:
        agent_name: Nombre del agente ("venta", "cita", "reserva")
        message: Mensaje del cliente
        session_id: ID de sesión para contexto (int, unificado con n8n)
        context: Contexto adicional (config del bot, etc.)
    
    Returns:
        Respuesta del agente MCP o None si hay error
    """
    circuit_breaker = await _get_circuit_breaker(agent_name)
    
    # Verificar circuit breaker
    if not await circuit_breaker.can_attempt():
        logger.warning("Circuit abierto para %s, rechazando request", agent_name)
        return None
    
    # Retry con backoff exponencial
    max_retries = app_config.MCP_MAX_RETRIES
    last_error = None
    
    for attempt in range(max_retries):
        try:
            result = await _invoke_mcp_agent_internal(agent_name, message, session_id, context)
            
            if result is not None:
                await circuit_breaker.record_success()
                if attempt > 0:
                    logger.info("Éxito después de %s intentos", attempt + 1)
                return result
            else:
                # Resultado None se considera fallo
                last_error = "Respuesta None del agente"
                await circuit_breaker.record_failure()

        except asyncio.TimeoutError:
            last_error = f"Timeout (>{app_config.MCP_TIMEOUT}s)"
            await circuit_breaker.record_failure()
            logger.warning("Timeout en intento %s/%s", attempt + 1, max_retries)

        except Exception as e:
            last_error = str(e)
            await circuit_breaker.record_failure()
            logger.warning("Error en intento %s/%s: %s", attempt + 1, max_retries, e)
        
        if attempt < max_retries - 1:
            backoff_time = 2 ** attempt
            logger.info("Esperando %ss antes de reintentar...", backoff_time)
            await asyncio.sleep(backoff_time)
    
    logger.error(
        "Todos los intentos fallaron para %s. Último error: %s. Circuit: %s, Fallos: %s",
        agent_name, last_error, circuit_breaker.get_state(), circuit_breaker.failure_count
    )
    return None

