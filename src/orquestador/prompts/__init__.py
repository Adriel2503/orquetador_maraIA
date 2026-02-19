"""
Prompts del orquestador. Builder del system prompt.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).resolve().parent

# Singleton: se crea una sola vez al importar el módulo y se reutiliza en cada request
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(disabled_extensions=()),
)
_orquestador_template = _jinja_env.get_template("orquestador_system.j2")

_DEFAULTS: Dict[str, Any] = {
    "nombre_bot": "Asistente",
    "objetivo_principal": "ayudar a los clientes",
    "personalidad": "amable y profesional",
    "frase_saludo": "¡Hola! ¿En qué puedo ayudarte?",
    "frase_des": "¡Gracias por contactarnos!",
    "frase_no_sabe": "No tengo esa información; permíteme transferirte con un agente.",
    "frase_esc": "Te voy a comunicar con un agente para ayudarte mejor.",
    "modalidad": "citas",
}


def _apply_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(_DEFAULTS)
    for k, v in config.items():
        if v is not None and v != "":
            out[k] = v
    return out


def _modalidad_to_agent(modalidad: str) -> str:
    """
    Mapea modalidad (n8n envía "Ventas" o "Citas") a agent_key.

    Returns:
        agent_key ("venta" o "cita") para usar en el prompt. El label se deriva en el template como agent_key + "s".
    """
    m = (modalidad or "").lower()
    if "ventas" in m:
        return "venta"
    return "cita"


modalidad_to_agent = _modalidad_to_agent


def build_orquestador_system_prompt(config: Dict[str, Any]) -> str:
    """
    Construye el system prompt del orquestador a partir de la config (ChatConfig).

    Args:
        config: Diccionario con nombre_bot, modalidad, frases, etc.
                Puede venir de ChatConfig.model_dump() o similar.

    Returns:
        System prompt formateado.
    """
    variables = _apply_defaults(config)
    variables["agent_key"] = _modalidad_to_agent(variables.get("modalidad", ""))
    return _orquestador_template.render(**variables)


def build_orquestador_system_prompt_with_memory(
    config: Dict[str, Any],
    memory: List[Dict],
    contexto_negocio: Optional[str] = None,
) -> str:
    """
    Construye el system prompt del orquestador incluyendo historial de conversación.

    Args:
        config: Diccionario con nombre_bot, modalidad, frases, etc.
        memory: Lista de turnos previos [{"user": "...", "agent": "...", "response": "..."}]
        contexto_negocio: Información breve del negocio (~100 palabras) para responder preguntas básicas sin delegar.

    Returns:
        System prompt formateado con contexto de memoria.
    """
    # Variables base del template
    variables = _apply_defaults(config)
    variables["agent_key"] = _modalidad_to_agent(variables.get("modalidad", ""))
    variables["contexto_negocio"] = (contexto_negocio or "").strip() or None

    # Detectar agente activo
    current_agent = None
    if memory:
        for turn in reversed(memory):
            if turn.get("agent"):
                current_agent = turn["agent"]
                break
    
    # Construir texto del historial
    history_text = ""
    if memory:
        history_lines = []
        for turn in memory[-5:]:  # Últimos 5 turnos
            agent_info = f" (derivaste a: {turn['agent']})" if turn['agent'] else " (respondiste directo)"
            history_lines.append(f"- Usuario: \"{turn['user']}\"")
            history_lines.append(f"  Respondiste: \"{turn['response']}\"{agent_info}")
        history_text = "\n".join(history_lines)
    
    # Agregar contexto de memoria
    variables["has_memory"] = bool(memory)
    variables["current_agent"] = current_agent
    variables["history_text"] = history_text

    return _orquestador_template.render(**variables)


__all__ = [
    "build_orquestador_system_prompt",
    "build_orquestador_system_prompt_with_memory",
    "modalidad_to_agent",
]
