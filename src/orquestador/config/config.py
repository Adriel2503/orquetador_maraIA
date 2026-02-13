"""
Configuración del orquestador (env, URLs MCP, modo monolítico).
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# .env en la raíz del proyecto orquestador (orquestador/.env)
_BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_BASE_DIR / ".env")

# Versión del servicio (única fuente de verdad)
VERSION = "0.3.0"

# =============================================================================
# MODO DE EJECUCIÓN DE AGENTES
# =============================================================================
# "local" = invocación directa (monolítico, para FileZilla)
# "mcp"   = invocación vía HTTP/MCP (microservicios, con Docker)
AGENT_MODE = os.getenv("AGENT_MODE", "local")

# =============================================================================
# CONFIGURACIÓN DE PATHS PARA MODO MONOLÍTICO
# =============================================================================
# Estructura en producción (FileZilla):
# /maravia/agente_service/
# ├── orquestador/src/orquestador/...
# ├── agente_citas/src/citas/...
# ├── agente_ventas/src/ventas/...
# └── agente_reservas/src/reservas/...

# Nombres de carpetas de los agentes
AGENT_FOLDERS = {
    "cita": "agente_citas",
    "ventas": "agente_ventas",
    "reserva": "agente_reservas",
}

def _setup_agent_paths():
    """
    Configura sys.path para poder importar los agentes hermanos.
    """
    # _BASE_DIR apunta a: .../orquestador/
    # Subir un nivel para llegar a agente_service/
    agente_service_dir = _BASE_DIR.parent

    paths_added = []

    for agente_name, carpeta in AGENT_FOLDERS.items():
        agente_path = agente_service_dir / carpeta / "src"
        if agente_path.exists() and str(agente_path) not in sys.path:
            sys.path.insert(0, str(agente_path))
            paths_added.append(str(agente_path))

    return paths_added

# Configurar paths al importar el módulo (solo en modo local)
_AGENT_PATHS = []
if AGENT_MODE == "local":
    _AGENT_PATHS = _setup_agent_paths()

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

# =============================================================================
# CONFIGURACIÓN DE LOGS
# =============================================================================
# Estructura: /maravia/agente_service/logs/
# _BASE_DIR = .../orquestador/
# _BASE_DIR.parent = .../agente_service/
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = _BASE_DIR.parent / "logs"
LOG_FILE = LOG_DIR / "orquestador.log"
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))  # 10MB default
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))  # 5 backups
