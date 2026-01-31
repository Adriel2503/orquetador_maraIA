# Arquitectura del Sistema - MaravIA Orquestador

Documentacion tecnica de la arquitectura del agente orquestador.

---

## Tabla de Contenidos

1. [Vision General](#vision-general)
2. [Diagrama de Arquitectura](#diagrama-de-arquitectura)
3. [Componentes del Sistema](#componentes-del-sistema)
4. [Flujo de Datos](#flujo-de-datos)
5. [Patrones de Diseno](#patrones-de-diseno)
6. [Integraciones Externas](#integraciones-externas)
7. [Modelo de Datos](#modelo-de-datos)
8. [Sistema de Prompts](#sistema-de-prompts)
9. [Concurrencia y Sincronizacion](#concurrencia-y-sincronizacion)
10. [Stack Tecnologico](#stack-tecnologico)

---

## Vision General

El Orquestador es un **router inteligente de conversaciones** que actua como punto de entrada unico para el sistema de agentes de MaravIA. Su funcion principal es:

1. **Recibir** mensajes de usuarios via n8n
2. **Analizar** la intencion usando OpenAI con structured output
3. **Decidir** si delegar a un agente especializado o responder directamente
4. **Mantener** contexto conversacional entre turnos
5. **Retornar** respuestas coherentes al usuario

### Principios de Diseno

- **Separacion de responsabilidades**: Cada modulo tiene una funcion especifica
- **Resiliencia**: Circuit breaker y retry para tolerancia a fallos
- **Observabilidad**: Logging estructurado y metricas
- **Escalabilidad**: Arquitectura stateless (excepto memoria in-memory)
- **Mantenibilidad**: Prompts externalizados en templates

---

## Diagrama de Arquitectura

```
                                    ┌─────────────────────────────────────────┐
                                    │              ORQUESTADOR                │
                                    │            (FastAPI App)                │
┌──────────┐    ┌──────────┐       │  ┌─────────────────────────────────┐   │
│          │    │          │       │  │           main.py               │   │
│  Usuario │───►│   n8n    │──────►│  │     (Flujo principal)           │   │
│          │    │          │       │  └──────────────┬──────────────────┘   │
└──────────┘    └──────────┘       │                 │                      │
                                    │    ┌───────────┼───────────┐          │
                                    │    ▼           ▼           ▼          │
                                    │ ┌──────┐  ┌─────────┐  ┌────────┐    │
                                    │ │memory│  │ prompts │  │  llm   │    │
                                    │ │ .py  │  │  /*.j2  │  │  .py   │    │
                                    │ └──────┘  └─────────┘  └────┬───┘    │
                                    │                              │        │
                                    │                              ▼        │
                                    │                        ┌──────────┐   │
                                    │                        │  OpenAI  │   │
                                    │                        │(gpt-4o-m)│   │
                                    │                        └──────────┘   │
                                    │                                       │
                                    │  ┌─────────────────────────────────┐  │
                                    │  │        mcp_client.py            │  │
                                    │  │  ┌─────────────────────────┐    │  │
                                    │  │  │    Circuit Breaker      │    │  │
                                    │  │  │    + Retry Backoff      │    │  │
                                    │  │  └───────────┬─────────────┘    │  │
                                    │  └──────────────┼──────────────────┘  │
                                    └─────────────────┼─────────────────────┘
                                                      │
                    ┌─────────────────────────────────┼─────────────────────────────────┐
                    │                                 │                                 │
                    ▼                                 ▼                                 ▼
            ┌──────────────┐                 ┌──────────────┐                 ┌──────────────┐
            │   Agente     │                 │   Agente     │                 │   Agente     │
            │   RESERVA    │                 │    VENTA     │                 │    CITA      │
            │  (MCP:8003)  │                 │  (MCP:8001)  │                 │  (MCP:8002)  │
            │   [ACTIVO]   │                 │ [PENDIENTE]  │                 │ [PENDIENTE]  │
            └──────────────┘                 └──────────────┘                 └──────────────┘
```

---

## Componentes del Sistema

### 1. main.py - Aplicacion FastAPI

**Responsabilidad**: Orquestar el flujo completo de request/response.

```python
# Flujo simplificado
async def chat(request: ChatRequest):
    # 1. Validar inputs
    # 2. Cargar memoria de sesion
    # 3. Obtener contexto de negocio
    # 4. Construir system prompt
    # 5. Invocar OpenAI (decision)
    # 6. Si delegate -> llamar MCP
    # 7. Guardar en memoria
    # 8. Retornar response
```

**Endpoints expuestos:**
- `POST /api/agent/chat` - Endpoint principal
- `GET /health` - Health check
- `GET /config` - Configuracion
- `GET /metrics` - Metricas
- `GET/POST /memory/*` - Gestion de memoria

### 2. llm.py - Cliente OpenAI

**Responsabilidad**: Comunicacion con OpenAI usando structured output.

```python
# Arquitectura
┌─────────────────────────────────────────────┐
│                  llm.py                     │
├─────────────────────────────────────────────┤
│  _llm: ChatOpenAI (lazy init)               │
│  _structured_llm: ChatOpenAI + schema       │
│  _llm_lock: asyncio.Lock                    │
├─────────────────────────────────────────────┤
│  invoke_orquestador(prompt, msg)            │
│    -> (response, agent_name)                │
└─────────────────────────────────────────────┘
```

**Caracteristicas:**
- Lazy initialization con lock async-safe
- Structured output con Pydantic schema
- Temperature 0.4 (respuestas deterministas)
- Timeout configurable (default 60s)

### 3. mcp_client.py - Cliente MCP

**Responsabilidad**: Comunicacion con agentes especializados via MCP.

```python
# Arquitectura
┌─────────────────────────────────────────────┐
│              mcp_client.py                  │
├─────────────────────────────────────────────┤
│  CircuitBreaker                             │
│    - failure_threshold: 5                   │
│    - reset_timeout: 60s                     │
│    - states: CLOSED -> OPEN -> HALF_OPEN    │
├─────────────────────────────────────────────┤
│  _circuit_breakers: Dict[agent, CB]         │
│  _mcp_client: MultiServerMCPClient          │
├─────────────────────────────────────────────┤
│  invoke_mcp_agent(agent, msg, session, ctx) │
│    - Circuit breaker check                  │
│    - Retry con backoff exponencial          │
│    - Timeout por llamada                    │
└─────────────────────────────────────────────┘
```

### 4. memory.py - Sistema de Memoria

**Responsabilidad**: Almacenar historial conversacional por sesion.

```python
# Estructura de almacenamiento
_MEMORY_STORE: Dict[str, List[Dict]] = {
    "session_123": [
        {
            "user": "Quiero reservar",
            "agent": None,
            "response": "Claro, para cuando?",
            "timestamp": "2025-01-30T15:30:00"
        },
        {
            "user": "Para manana",
            "agent": "reserva",
            "response": "Tengo disponibilidad...",
            "timestamp": "2025-01-30T15:31:00"
        }
    ]
}
```

**Caracteristicas:**
- In-memory (Dict protegido con asyncio.Lock)
- Maximo 10 turnos por sesion
- Metodos: add, get, get_current_agent, clear, get_stats

### 5. prompts/ - Sistema de Prompts

**Responsabilidad**: Construir system prompts dinamicos.

```
prompts/
├── __init__.py                    # Builder functions
└── orquestador_system.j2          # Template Jinja2
```

**Variables del template:**
- Configuracion del bot (nombre, personalidad, frases)
- Contexto de negocio (informacion de la empresa)
- Historial conversacional (ultimos 5 turnos)
- Agente activo (si hay delegacion en curso)

### 6. config.py - Configuracion

**Responsabilidad**: Centralizar configuracion desde variables de entorno.

```python
# Categorias de configuracion
VERSION = "0.2.0"

# URLs MCP
MCP_RESERVA_URL = "http://localhost:8003/mcp"
MCP_CITA_URL = "http://localhost:8002/mcp"
MCP_VENTA_URL = "http://localhost:8001/mcp"

# Timeouts
MCP_TIMEOUT = 30
OPENAI_TIMEOUT = 60
CONTEXTO_NEGOCIO_TIMEOUT = 10

# Circuit Breaker
MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5
MCP_CIRCUIT_BREAKER_RESET_TIMEOUT = 60
MCP_MAX_RETRIES = 3

# OpenAI
OPENAI_MODEL = "gpt-4o-mini"
```

### 7. models.py - Modelos Pydantic

**Responsabilidad**: Validacion de datos de entrada/salida.

```python
# Modelos principales
ChatConfig       # Configuracion del bot
ChatRequest      # Request de n8n
ChatResponse     # Response a n8n
OrquestradorDecision  # Structured output de OpenAI
```

### 8. logging_config.py - Logging

**Responsabilidad**: Logging estructurado en JSON.

```json
{
  "timestamp": "2025-01-30T15:30:00.123456+00:00",
  "level": "INFO",
  "logger": "orquestador.main",
  "message": "POST /api/agent/chat request",
  "session_id": "user_123",
  "agent_to_invoke": "reserva"
}
```

### 9. metrics.py - Metricas

**Responsabilidad**: Recolectar metricas de rendimiento.

```python
# Metricas recolectadas
_requests_total = 0
_requests_errors = 0
_requests_delegate = 0
_requests_respond = 0
_latencies: List[float] = []  # Ultimas 100 muestras
```

---

## Flujo de Datos

### Flujo Completo de un Request

```
1. REQUEST ENTRANTE
   ┌─────────────────────────────────────────────────────┐
   │ POST /api/agent/chat                                │
   │ {message, session_id, config}                       │
   └────────────────────────┬────────────────────────────┘
                            │
2. VALIDACION               ▼
   ┌─────────────────────────────────────────────────────┐
   │ - message no vacio                                  │
   │ - session_id no vacio                               │
   │ - id_empresa > 0                                    │
   └────────────────────────┬────────────────────────────┘
                            │
3. CARGAR CONTEXTO          ▼
   ┌─────────────────────────────────────────────────────┐
   │ Paralelo:                                           │
   │ - memory_manager.get(session_id)                    │
   │ - fetch_contexto_negocio(id_empresa)                │
   └────────────────────────┬────────────────────────────┘
                            │
4. CONSTRUIR PROMPT         ▼
   ┌─────────────────────────────────────────────────────┐
   │ build_orquestador_system_prompt_with_memory(        │
   │   config, memory, contexto_negocio                  │
   │ )                                                   │
   │ -> Renderiza template Jinja2                        │
   └────────────────────────┬────────────────────────────┘
                            │
5. DECISION (OpenAI)        ▼
   ┌─────────────────────────────────────────────────────┐
   │ invoke_orquestador(system_prompt, message)          │
   │ -> OrquestradorDecision {action, agent_name, resp}  │
   └────────────────────────┬────────────────────────────┘
                            │
                   ┌────────┴────────┐
                   │                 │
6a. RESPOND        ▼                 ▼  6b. DELEGATE
   ┌──────────────────┐      ┌─────────────────────────┐
   │ action="respond" │      │ action="delegate"       │
   │ final_reply=resp │      │ invoke_mcp_agent(...)   │
   │ agent_used=null  │      │ final_reply=mcp_resp    │
   └────────┬─────────┘      │ agent_used=agent_name   │
            │                └───────────┬─────────────┘
            │                            │
            └─────────────┬──────────────┘
                          │
7. GUARDAR MEMORIA        ▼
   ┌─────────────────────────────────────────────────────┐
   │ memory_manager.add(session_id, message,             │
   │                    agent_used, final_reply)         │
   └────────────────────────┬────────────────────────────┘
                            │
8. RESPONSE                 ▼
   ┌─────────────────────────────────────────────────────┐
   │ ChatResponse {reply, session_id, agent_used, action}│
   └─────────────────────────────────────────────────────┘
```

### Flujo de Delegacion MCP

```
invoke_mcp_agent(agent_name, message, session_id, context)
                            │
                            ▼
              ┌─────────────────────────────┐
              │   Circuit Breaker Check     │
              │   cb.can_attempt()?         │
              └──────────────┬──────────────┘
                             │
              ┌──────────────┴──────────────┐
              │ NO                          │ YES
              ▼                             ▼
       ┌──────────────┐        ┌─────────────────────────┐
       │ Return None  │        │ for attempt in retries: │
       │ (circuit     │        │   try:                  │
       │  open)       │        │     result = mcp_call() │
       └──────────────┘        │     cb.record_success() │
                               │     return result       │
                               │   except:               │
                               │     cb.record_failure() │
                               │     backoff(2^attempt)  │
                               └─────────────────────────┘
```

---

## Patrones de Diseno

### 1. Circuit Breaker Pattern

Protege contra fallos en cascada cuando un agente MCP esta caido.

```
Estados:
CLOSED ──[5 fallos]──> OPEN ──[60s timeout]──> HALF_OPEN
   ▲                                               │
   │                    ┌──────────────────────────┘
   │                    │
   │              [1 exito]     [1 fallo]
   │                    │           │
   └────────────────────┘           ▼
                                  OPEN
```

**Configuracion:**
- `failure_threshold`: 5 fallos consecutivos para abrir
- `reset_timeout`: 60 segundos antes de probar recuperacion

### 2. Retry con Backoff Exponencial

Reintenta llamadas fallidas con delays crecientes.

```
Intento 1 -> Falla -> Espera 1s
Intento 2 -> Falla -> Espera 2s
Intento 3 -> Falla -> Error final
```

**Formula:** `delay = 2^attempt` segundos

### 3. Lazy Initialization

Los clientes (OpenAI, MCP) se inicializan en el primer uso, no al arrancar.

```python
async def _get_structured_llm():
    async with _llm_lock:
        if _structured_llm is None:
            _create_llm_if_needed()
            _structured_llm = _llm.with_structured_output(schema)
    return _structured_llm
```

**Beneficios:**
- Arranque rapido
- Fail-fast solo cuando se usa el recurso
- Proteccion contra race conditions con asyncio.Lock

### 4. Structured Output

Garantiza respuestas JSON validas desde OpenAI.

```python
class OrquestradorDecision(BaseModel):
    action: Literal["delegate", "respond"]
    agent_name: Optional[Literal["reserva", "venta", "cita"]]
    response: str

# OpenAI siempre retorna JSON valido segun este schema
structured_llm = llm.with_structured_output(OrquestradorDecision)
```

### 5. Template Pattern (Prompts)

Separa la logica del prompt del codigo Python.

```
Python (builder) ─────> Jinja2 (template) ─────> String (prompt)
     │                        │
     └── variables ───────────┘
```

---

## Integraciones Externas

### 1. OpenAI API

**Proposito**: Analisis de intencion y generacion de respuestas.

```
Orquestador ──HTTP──> api.openai.com
                      POST /v1/chat/completions
```

**Configuracion:**
- Modelo: `gpt-4o-mini` (default) o `gpt-4o`
- Temperature: 0.4
- Max tokens: 4096
- Timeout: 60s

### 2. Agentes MCP

**Proposito**: Procesamiento especializado (reservas, ventas, citas).

```
Orquestador ──HTTP──> localhost:8003/mcp  (Reserva)
            ──HTTP──> localhost:8001/mcp  (Venta - pendiente)
            ──HTTP──> localhost:8002/mcp  (Cita - pendiente)
```

**Protocolo**: Model Context Protocol (MCP)
- Tool: "chat"
- Args: {message, session_id, context}

### 3. API Contexto de Negocio

**Proposito**: Obtener informacion de la empresa para respuestas basicas.

```
Orquestador ──HTTP POST──> api.maravia.pe/servicio/ws_informacion_ia.php
                           {codOpe: "OBTENER_CONTEXTO_NEGOCIO", id_empresa: X}
```

**Response esperado:**
```json
{
  "success": true,
  "contexto_negocio": "Somos un spa especializado en..."
}
```

---

## Modelo de Datos

### Estructura de Memoria

```python
# Por sesion
{
    "user": str,           # Mensaje del usuario
    "agent": str | None,   # Agente que proceso (si hubo delegacion)
    "response": str,       # Respuesta final
    "timestamp": str       # ISO-8601
}
```

### Flujo de Datos entre Componentes

```
ChatRequest                    ChatResponse
    │                               ▲
    ▼                               │
┌─────────┐                   ┌─────────┐
│ message │                   │  reply  │
│session_id│                   │session_id│
│ config  │                   │agent_used│
└────┬────┘                   │ action  │
     │                        └────┬────┘
     ▼                             │
┌──────────────────────────────────┴──┐
│           Procesamiento             │
│  ┌────────────┐  ┌────────────────┐ │
│  │   Memory   │  │ OrquestradorD. │ │
│  │ List[Dict] │  │ action/agent/  │ │
│  └────────────┘  │ response       │ │
│                  └────────────────┘ │
└─────────────────────────────────────┘
```

---

## Sistema de Prompts

### Template Jinja2

El system prompt se construye dinamicamente con estas secciones:

```
1. IDENTIDAD
   - Nombre del bot
   - Objetivo principal
   - Modalidad y personalidad

2. CONTEXTO DE NEGOCIO (opcional)
   - Informacion de la empresa
   - Permite responder sin delegar

3. ESTADO DE CONVERSACION (si hay memoria)
   - Agente activo (si existe)
   - Reglas de continuidad
   - Historial reciente (5 turnos)

4. REGLAS DE DELEGACION
   - Cuando delegar a cada agente
   - Palabras clave por agente

5. REGLAS DE RESPUESTA DIRECTA
   - Saludos, despedidas
   - Ambiguedades, escalamiento

6. FORMATO DE SALIDA
   - Schema JSON esperado
   - Ejemplos de uso
```

### Variables Dinamicas

| Variable | Fuente | Default |
|----------|--------|---------|
| `nombre_bot` | config | "Asistente" |
| `objetivo_principal` | config | "ayudar a los clientes" |
| `personalidad` | config | "amable y profesional" |
| `frase_saludo` | config | "Hola! En que puedo ayudarte?" |
| `contexto_negocio` | API externa | null |
| `has_memory` | memoria | false |
| `current_agent` | memoria | null |
| `history_text` | memoria | "" |

---

## Concurrencia y Sincronizacion

### Recursos Protegidos

```python
# llm.py
_llm_lock = asyncio.Lock()  # Protege init de LLM

# mcp_client.py
_circuit_breakers_lock = asyncio.Lock()  # Protege dict de CBs

# memory.py
_memory_lock = asyncio.Lock()  # Protege MEMORY_STORE
```

### Patron de Uso

```python
async with _memory_lock:
    # Operacion atomica sobre _MEMORY_STORE
    _MEMORY_STORE[session_id].append(turn)
```

### Consideraciones

- Todo el flujo es **async/await**
- Los locks son **asyncio.Lock** (no threading.Lock)
- Las operaciones de I/O (OpenAI, MCP) usan **await**
- El contexto de negocio usa `asyncio.to_thread()` para llamada sync

---

## Stack Tecnologico

### Core

| Componente | Tecnologia | Version |
|------------|------------|---------|
| Runtime | Python | 3.12 |
| Framework | FastAPI | >= 0.104.0 |
| Server | uvicorn | >= 0.24.0 |
| Validacion | Pydantic | >= 2.0.0 |

### LLM

| Componente | Tecnologia | Version |
|------------|------------|---------|
| Base | LangChain Core | >= 0.2.0 |
| OpenAI | LangChain OpenAI | >= 0.1.0 |
| Cliente | OpenAI Python | >= 1.0.0 |

### MCP

| Componente | Tecnologia | Version |
|------------|------------|---------|
| Cliente | langchain-mcp-adapters | >= 0.1.0 |

### Utilidades

| Componente | Tecnologia | Version |
|------------|------------|---------|
| Templating | Jinja2 | >= 3.1.0 |
| Env vars | python-dotenv | >= 1.0.0 |

### Infraestructura

| Componente | Tecnologia |
|------------|------------|
| Contenedor | Docker |
| Compose | Docker Compose |
| Puerto | 8000 |

---

*Arquitectura documentada para MaravIA Orquestador v0.2.0*
