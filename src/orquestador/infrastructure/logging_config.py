"""
Logging estructurado en JSON para el orquestador.
Cada línea es un objeto JSON con timestamp, level, message, logger y campos extra.

Soporta salida dual: stdout + archivo con rotación automática.
Configuración en config.py: LOG_LEVEL, LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT
"""

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional


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
    log_file: Optional[Path] = None,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    use_json: bool = True,
) -> None:
    """
    Configura el logging del orquestador.

    Args:
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path al archivo de log (None = solo stdout)
        max_bytes: Tamaño máximo del archivo antes de rotar (default 10MB)
        backup_count: Número de backups a mantener (default 5)
        use_json: Si True, usa formato JSON; si False, formato texto
    """
    root = logging.getLogger("orquestador")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Evitar handlers duplicados
    if root.handlers:
        return

    formatter = JsonFormatter() if use_json else logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # Handler para stdout (siempre activo)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root.addHandler(stdout_handler)

    # Handler para archivo (si se especifica)
    if log_file:
        try:
            # Crear directorio si no existe
            log_dir = log_file.parent
            log_dir.mkdir(parents=True, exist_ok=True)

            file_handler = RotatingFileHandler(
                filename=str(log_file),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)

            # Log inicial para confirmar que el archivo está funcionando
            root.info(
                "Logging a archivo iniciado",
                extra={"extra_fields": {"log_file": str(log_file)}}
            )
        except Exception as e:
            root.warning(
                "No se pudo configurar logging a archivo: %s. Solo se usará stdout.",
                str(e)
            )

    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    """Devuelve un logger bajo el namespace orquestador."""
    if not name.startswith("orquestador."):
        name = f"orquestador.{name}"
    return logging.getLogger(name)


def _init_logging_from_config() -> None:
    """
    Inicializa logging usando la configuración de config.py.
    Se llama automáticamente al importar este módulo.
    """
    try:
        from ..config import config as app_config
    except ImportError:
        try:
            from orquestador.config import config as app_config
        except ImportError:
            # Fallback si no se puede importar config
            setup_logging()
            return

    setup_logging(
        level=app_config.LOG_LEVEL,
        log_file=app_config.LOG_FILE,
        max_bytes=app_config.LOG_MAX_BYTES,
        backup_count=app_config.LOG_BACKUP_COUNT,
    )


# Inicializar al importar
_init_logging_from_config()

__all__ = ["get_logger", "setup_logging", "JsonFormatter"]
