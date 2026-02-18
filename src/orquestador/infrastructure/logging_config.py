"""
Logging estructurado en JSON para el orquestador.
Cada línea es un objeto JSON con timestamp, level, message, logger y campos extra.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict


class JsonFormatter(logging.Formatter):
    """Formatea cada registro como una línea JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        # Cualquier extra pasado con logger.info(..., extra={"key": "value"})
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_obj.update(record.extra_fields)
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    stream=None,
    use_json: bool = True,
) -> None:
    """
    Configura el logging del orquestador.
    Por defecto salida JSON a stdout.
    """
    if stream is None:
        stream = sys.stdout
    root = logging.getLogger("orquestador")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not root.handlers:
        handler = logging.StreamHandler(stream)
        if use_json:
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            )
        root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Devuelve un logger bajo el namespace orquestador."""
    if not name.startswith("orquestador."):
        name = f"orquestador.{name}"
    return logging.getLogger(name)


# Inicializar al importar (nivel INFO por defecto)
# Wrappear en try/except para evitar fallar silenciosamente si hay error de permisos
try:
    setup_logging()
except Exception as e:
    import sys
    print(f"Warning: Error configurando logging: {e}", file=sys.stderr)

__all__ = ["get_logger", "setup_logging", "JsonFormatter"]
