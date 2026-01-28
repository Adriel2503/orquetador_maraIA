"""
Configuración del orquestador (env, URLs MCP).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env en la raíz del proyecto orquestador
_BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(_BASE_DIR / ".env")

# URLs de servidores MCP (Venta, Cita, Reserva)
MCP_RESERVA_URL = os.getenv("MCP_RESERVA_URL", "http://localhost:8003/mcp")
MCP_CITA_URL = os.getenv("MCP_CITA_URL", "http://localhost:8002/mcp")
MCP_VENTA_URL = os.getenv("MCP_VENTA_URL", "http://localhost:8001/mcp")

# Opcional: activar/desactivar llamadas a MCP Reserva sin cambiar código
MCP_RESERVA_ENABLED = os.getenv("MCP_RESERVA_ENABLED", "true").lower() in ("1", "true", "yes")

# OpenAI (agente orquestador)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
