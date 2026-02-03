# MaravIA Orquestador

Agente orquestador inteligente que enruta conversaciones a agentes especializados mediante el protocolo MCP (Model Context Protocol).

## Descripcion

El Orquestador es el punto de entrada central del sistema de agentes de MaravIA. Recibe mensajes de usuarios (via n8n), analiza la intencion usando OpenAI con structured output, y decide si:

- **Delegar** a un agente especializado (Reserva, Venta, Cita)
- **Responder directamente** para consultas simples

```
Usuario → n8n → Orquestador → [OpenAI Decision] → Agente MCP → Respuesta
                    ↓
              Respuesta directa
```

## Caracteristicas

- **Deteccion de intencion** con OpenAI Structured Output (JSON garantizado)
- **Memoria conversacional** - Mantiene contexto de ultimos 10 turnos
- **Delegacion inteligente** a agentes MCP especializados
- **Circuit Breaker** - Proteccion contra fallos en cascada
- **Retry con backoff exponencial** - Resiliencia en llamadas MCP
- **Logging estructurado JSON** - Listo para ELK/CloudWatch
- **Metricas in-memory** - Monitoreo de rendimiento

## Inicio Rapido

### Requisitos

- Python 3.12+
- OpenAI API Key
- (Opcional) Agentes MCP corriendo

### Instalacion

```bash
# Clonar repositorio
git clone <repo-url>
cd orquestador

# Crear entorno virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tu OPENAI_API_KEY
```

### Ejecucion Local

```bash
# Opcion 1: Directamente
python -m src.orquestador.api.main

# Opcion 2: Con uvicorn
uvicorn src.orquestador.api.main:app --reload --host 0.0.0.0 --port 8000
```

### Ejecucion con Docker

```bash
# Construir y ejecutar
docker-compose up --build

# O con Docker directamente
docker build -t maravia-orquestador .
docker run -p 8000:8000 --env-file .env maravia-orquestador
```

## Uso

### Endpoint Principal

```bash
POST /api/agent/chat
```

**Request:**
```json
{
  "message": "Quiero reservar un turno para manana",
  "session_id": "usuario_123",
  "config": {
    "nombre_bot": "Asistente MaravIA",
    "id_empresa": 5,
    "rol_bot": "asistente",
    "tipo_bot": "reservas",
    "objetivo_principal": "ayudar a los clientes con reservas"
  }
}
```

**Response:**
```json
{
  "reply": "Perfecto, dejame revisar la disponibilidad para manana. Que horario prefieres?",
  "session_id": "usuario_123",
  "agent_used": "reserva",
  "action": "delegate"
}
```

### Otros Endpoints

| Endpoint | Metodo | Descripcion |
|----------|--------|-------------|
| `/` | GET | Informacion del servicio |
| `/health` | GET | Health check |
| `/config` | GET | Configuracion actual |
| `/metrics` | GET | Metricas y circuit breakers |
| `/memory/stats` | GET | Estadisticas de memoria |
| `/memory/clear/{session_id}` | POST | Limpiar sesion |
| `/docs` | GET | Swagger UI |
| `/redoc` | GET | ReDoc |

## Configuracion

Variables de entorno disponibles (ver `.env.example`):

```env
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_TIMEOUT=60

# MCP Agents
MCP_RESERVA_URL=http://localhost:8003/mcp
MCP_RESERVA_ENABLED=true
MCP_TIMEOUT=30
MCP_MAX_RETRIES=3

# Circuit Breaker
MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
MCP_CIRCUIT_BREAKER_RESET_TIMEOUT=60

# Contexto de Negocio
CONTEXTO_NEGOCIO_ENDPOINT=https://api.maravia.pe/servicio/ws_informacion_ia.php
CONTEXTO_NEGOCIO_TIMEOUT=10
```

## Estructura del Proyecto

```
orquestador/
├── src/
│   └── orquestador/
│       ├── __init__.py
│       ├── api/
│       │   ├── __init__.py
│       │   └── main.py          # FastAPI app principal
│       ├── config/
│       │   ├── __init__.py
│       │   ├── config.py        # Configuracion y env vars
│       │   └── models.py        # Modelos Pydantic
│       ├── integrations/
│       │   ├── __init__.py
│       │   ├── llm.py           # Cliente OpenAI
│       │   └── mcp_client.py    # Cliente MCP + Circuit Breaker
│       ├── services/
│       │   ├── __init__.py
│       │   └── memory.py        # Memoria conversacional
│       ├── infrastructure/
│       │   ├── __init__.py
│       │   ├── logging_config.py  # Logging JSON
│       │   └── metrics.py        # Metricas
│       └── prompts/
│           ├── __init__.py      # Builder de prompts
│           └── orquestador_system.j2  # Template Jinja2
├── docs/
│   ├── api.md                   # Documentacion de APIs
│   ├── architecture.md          # Arquitectura del sistema
│   ├── deployment.md            # Guia de despliegue
│   └── agent-review.md          # Revision tecnica
├── Dockerfile
├── compose.yaml
├── requirements.txt
├── .env.example
└── README.md
```

## Documentacion

- [API Reference](docs/api.md) - Documentacion completa de endpoints
- [Arquitectura](docs/architecture.md) - Diseno del sistema
- [Despliegue](docs/deployment.md) - Guia de deployment
- [Revision Tecnica](docs/agent-review.md) - Analisis y recomendaciones

## Agentes Especializados

| Agente | Puerto | Estado | Funcion |
|--------|--------|--------|---------|
| Reserva | 8003 | Activo | Gestion de turnos y reservas |
| Venta | 8001 | En desarrollo | Cotizaciones y ventas |
| Cita | 8002 | En desarrollo | Agendamiento de reuniones |

## Stack Tecnologico

- **Framework**: FastAPI
- **LLM**: OpenAI (gpt-4o-mini/gpt-4o) via LangChain
- **MCP**: langchain-mcp-adapters
- **Templating**: Jinja2
- **Validacion**: Pydantic v2
- **Runtime**: Python 3.12, uvicorn

## Version

**v0.2.0** - Produccion v1 con memoria conversacional y contexto de negocio

## Licencia

Propiedad de MaravIA - Uso interno

---

*Desarrollado por el equipo de AI de MaravIA*
