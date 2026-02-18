"""
Configuración del orquestador (env, URLs MCP).
"""

import os
from pathlib import Path

from dotenv import load_dotenv, find_dotenv

# Buscar .env hacia arriba desde este archivo hasta encontrarlo o llegar a raíz.
# find_dotenv() es robusto y funciona independientemente de dónde se ejecute.
_ENV_FILE = find_dotenv(usecwd=True)
if _ENV_FILE:
    load_dotenv(_ENV_FILE)
else:
    # Si no encuentra .env, intenta en la estructura esperada (fallback)
    _BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
    if (_BASE_DIR / ".env").exists():
        load_dotenv(_BASE_DIR / ".env")

# Versión del servicio (única fuente de verdad)
VERSION = "0.2.0"

# URLs de servidores MCP (Venta, Cita, Reserva)
MCP_RESERVA_URL = os.getenv("MCP_RESERVA_URL", "http://localhost:8003/mcp")
MCP_CITA_URL = os.getenv("MCP_CITA_URL", "http://localhost:8002/mcp")
MCP_VENTA_URL = os.getenv("MCP_VENTA_URL", "http://localhost:8001/mcp")

# Opcional: activar/desactivar llamadas a MCP Reserva sin cambiar código
MCP_RESERVA_ENABLED = os.getenv("MCP_RESERVA_ENABLED", "true").lower() in ("1", "true", "yes")

# Opcional: activar/desactivar llamadas a MCP Cita sin cambiar código
MCP_CITA_ENABLED = os.getenv("MCP_CITA_ENABLED", "true").lower() in ("1", "true", "yes")

# Endpoint para contexto de negocio (obtener información breve para el orquestador)
CONTEXTO_NEGOCIO_ENDPOINT = os.getenv(
    "CONTEXTO_NEGOCIO_ENDPOINT",
    "https://api.maravia.pe/servicio/ws_informacion_ia.php",
)
CONTEXTO_NEGOCIO_TIMEOUT = int(os.getenv("CONTEXTO_NEGOCIO_TIMEOUT", "10"))

# OpenAI (agente orquestador)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TIMEOUT = int(os.getenv("OPENAI_TIMEOUT", "60"))

# MCP (agentes especializados)
MCP_TIMEOUT = int(os.getenv("MCP_TIMEOUT", "30"))
MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv("MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5"))
MCP_CIRCUIT_BREAKER_RESET_TIMEOUT = int(os.getenv("MCP_CIRCUIT_BREAKER_RESET_TIMEOUT", "60"))
MCP_MAX_RETRIES = int(os.getenv("MCP_MAX_RETRIES", "3"))

# Timeout total del flujo completo chat (debe ser > OPENAI_TIMEOUT + MCP_TIMEOUT para el caso normal)
CHAT_TIMEOUT = int(os.getenv("CHAT_TIMEOUT", "120"))
