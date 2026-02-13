"""
Invocador local de agentes para modo monolítico.

Este módulo permite invocar agentes directamente sin usar HTTP/MCP,
importando y ejecutando sus funciones principales.

Estructura esperada en producción (FileZilla):
/maravia/agente_service/
├── orquestador/src/orquestador/...
├── agente_citas/src/citas/...
├── agente_ventas/src/ventas/...
└── agente_reservas/src/reservas/...
"""

from typing import Any, Dict, Optional

try:
    from ..infrastructure.logging_config import get_logger
except ImportError:
    from orquestador.infrastructure.logging_config import get_logger

logger = get_logger("agent_invoker")

# Cache de módulos importados para evitar reimportaciones
_agent_modules: Dict[str, Any] = {}


async def invoke_agent_local(
    agent_name: str,
    message: str,
    session_id: int,
    context: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    Invoca un agente localmente importando su módulo principal.

    Args:
        agent_name: Nombre del agente ("cita", "ventas", "reserva")
        message: Mensaje del cliente
        session_id: ID de sesión
        context: Contexto adicional (config del bot, etc.)

    Returns:
        Respuesta del agente o None si hay error
    """
    if context is None:
        context = {}

    logger.info(
        "Invocando agente local",
        extra={"extra_fields": {"agent": agent_name, "session_id": session_id}}
    )

    try:
        if agent_name == "cita":
            return await _invoke_citas(message, session_id, context)

        elif agent_name == "ventas":
            return await _invoke_ventas(message, session_id, context)

        elif agent_name == "reserva":
            return await _invoke_reservas(message, session_id, context)

        else:
            logger.warning("Agente desconocido: %s", agent_name)
            return None

    except ImportError as e:
        logger.error(
            "Error importando agente %s: %s. Verifica que el agente exista en la carpeta correcta.",
            agent_name, e
        )
        return None

    except Exception as e:
        logger.exception("Error ejecutando agente %s: %s", agent_name, e)
        return None


async def _invoke_citas(message: str, session_id: int, context: Dict[str, Any]) -> Optional[str]:
    """Invoca el agente de citas."""
    if "citas" not in _agent_modules:
        # Importación dinámica - el path ya fue configurado en config.py
        from citas.agent.agent import process_cita_message
        _agent_modules["citas"] = process_cita_message
        logger.info("Módulo citas importado correctamente")

    process_fn = _agent_modules["citas"]
    result = await process_fn(message=message, session_id=session_id, context=context)
    return result


async def _invoke_ventas(message: str, session_id: int, context: Dict[str, Any]) -> Optional[str]:
    """Invoca el agente de ventas."""
    if "ventas" not in _agent_modules:
        # Importación dinámica - el path ya fue configurado en config.py
        from ventas.agent.agent import process_venta_message
        _agent_modules["ventas"] = process_venta_message
        logger.info("Módulo ventas importado correctamente")

    process_fn = _agent_modules["ventas"]
    result = await process_fn(message=message, session_id=session_id, context=context)
    return result


async def _invoke_reservas(message: str, session_id: int, context: Dict[str, Any]) -> Optional[str]:
    """Invoca el agente de reservas."""
    if "reservas" not in _agent_modules:
        # Importación dinámica - el path ya fue configurado en config.py
        from reservas.agent.agent import process_reserva_message
        _agent_modules["reservas"] = process_reserva_message
        logger.info("Módulo reservas importado correctamente")

    process_fn = _agent_modules["reservas"]
    result = await process_fn(message=message, session_id=session_id, context=context)
    return result


def is_agent_available(agent_name: str) -> bool:
    """
    Verifica si un agente está disponible para importación.

    Args:
        agent_name: Nombre del agente ("cita", "ventas", "reserva")

    Returns:
        True si el agente puede ser importado
    """
    try:
        if agent_name == "cita":
            from citas.agent.agent import process_cita_message
            return True
        elif agent_name == "ventas":
            from ventas.agent.agent import process_venta_message
            return True
        elif agent_name == "reserva":
            from reservas.agent.agent import process_reserva_message
            return True
        return False
    except ImportError:
        return False


def get_available_agents() -> Dict[str, bool]:
    """
    Retorna un diccionario con la disponibilidad de cada agente.
    """
    return {
        "cita": is_agent_available("cita"),
        "ventas": is_agent_available("ventas"),
        "reserva": is_agent_available("reserva"),
    }
