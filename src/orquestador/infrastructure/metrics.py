"""
Métricas del orquestador exportadas en formato Prometheus.
Usa prometheus_client para contadores e histogramas.
Sin almacenamiento en memoria - Prometheus scrapeea y almacena en su DB.
"""

from prometheus_client import Counter, Histogram, generate_latest

# Contadores
requests_total = Counter(
    'orquestador_requests_total',
    'Total de requests procesadas',
    ['status']  # "success" | "error"
)

requests_by_action = Counter(
    'orquestador_requests_by_action_total',
    'Requests por tipo de acción',
    ['action']  # "delegate" | "respond"
)

# Histograma con buckets para latencias
request_duration = Histogram(
    'orquestador_request_duration_seconds',
    'Duración de requests en segundos',
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0)  # p50, p95, p99 calculados automáticamente
)

llm_agent_corrections_total = Counter(
    'orquestador_llm_agent_corrections_total',
    'Veces que se corrigió agent_name por desviación de modalidad',
    ['modalidad', 'llm_agent']
)


async def record_request(latency_seconds: float, action: str, error: bool = False) -> None:
    """
    Registra una request completada.
    
    Prometheus automáticamente mantiene totales, sumas y calcula percentiles.
    El /metrics endpoint scrapeea estos valores.
    
    Args:
        latency_seconds: Latencia de la request en segundos
        action: Acción realizada ("delegate" | "respond")
        error: Si ocurrió error (default False)
    """
    status = "error" if error else "success"
    requests_total.labels(status=status).inc()
    requests_by_action.labels(action=action).inc()
    request_duration.observe(latency_seconds)


def get_metrics_endpoint() -> bytes:
    """
    Genera la salida en formato Prometheus para el endpoint /metrics.
    Devuelve bytes listos para servir con content-type: text/plain; version=0.0.4
    """
    return generate_latest()


__all__ = [
    "record_request",
    "get_metrics_endpoint",
    "requests_total",
    "requests_by_action",
    "request_duration",
    "llm_agent_corrections_total",
]
