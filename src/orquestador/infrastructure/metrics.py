"""
Métricas in-memory del orquestador para observabilidad.
Contadores de requests, errores, latencia y estado de circuit breaker.
"""

import time
from typing import Dict, List, Any

# Contadores
_requests_total = 0
_requests_errors = 0
_requests_delegate = 0
_requests_respond = 0
# Latencias recientes (últimas N para promedio)
_latencies: List[float] = []
_LATENCY_SAMPLE_SIZE = 100


def record_request(latency_seconds: float, action: str, error: bool = False) -> None:
    """Registra una request completada."""
    global _requests_total, _requests_errors, _requests_delegate, _requests_respond, _latencies
    _requests_total += 1
    if error:
        _requests_errors += 1
    if action == "delegate":
        _requests_delegate += 1
    else:
        _requests_respond += 1
    _latencies.append(latency_seconds)
    if len(_latencies) > _LATENCY_SAMPLE_SIZE:
        _latencies.pop(0)


def get_metrics() -> Dict[str, Any]:
    """Devuelve todas las métricas en un dict (para JSON /metrics)."""
    avg_latency = sum(_latencies) / len(_latencies) if _latencies else 0.0
    return {
        "requests_total": _requests_total,
        "requests_errors": _requests_errors,
        "requests_delegate": _requests_delegate,
        "requests_respond": _requests_respond,
        "latency_avg_seconds": round(avg_latency, 4),
        "latency_samples": len(_latencies),
    }


def get_metrics_with_circuit_breakers(circuit_breaker_states: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Devuelve métricas incluyendo estado de circuit breakers por agente."""
    base = get_metrics()
    base["circuit_breakers"] = circuit_breaker_states
    return base
