# API Reference - MaravIA Orquestador

Documentacion completa de todos los endpoints del Orquestador.

**Base URL**: `http://localhost:8000`

**Version**: `0.2.0`

---

## Tabla de Contenidos

1. [Endpoint Principal - Chat](#endpoint-principal---chat)
2. [Endpoints de Informacion](#endpoints-de-informacion)
3. [Endpoints de Memoria](#endpoints-de-memoria)
4. [Endpoints de Monitoreo](#endpoints-de-monitoreo)
5. [Modelos de Datos](#modelos-de-datos)
6. [Codigos de Error](#codigos-de-error)

---

## Endpoint Principal - Chat

### POST `/api/agent/chat`

Endpoint principal que recibe mensajes de usuarios y devuelve respuestas del sistema de agentes.

#### Request

**Headers:**
```
Content-Type: application/json
```

**Body:**
```json
{
  "message": "string (requerido)",
  "session_id": "string (requerido)",
  "config": {
    "nombre_bot": "string (requerido)",
    "id_empresa": "integer > 0 (requerido)",
    "rol_bot": "string (requerido)",
    "tipo_bot": "string (requerido)",
    "objetivo_principal": "string (requerido)",
    "frase_saludo": "string (opcional)",
    "archivo_saludo": "string (opcional)",
    "personalidad": "string (opcional)",
    "tono_com": "string (opcional)",
    "frase_des": "string (opcional)",
    "frase_no_sabe": "string (opcional)",
    "modalidad": "string (opcional)",
    "temas_esc": "string (opcional)",
    "frase_esc": "string (opcional)",
    "motivo_der": "string (opcional)",
    "motivo_so": "string (opcional)",
    "fecha_formateada": "string (opcional)",
    "fecha_iso": "string (opcional)",
    "duracion_cita_minutos": "integer (opcional)",
    "slots": "integer (opcional)",
    "agendar_usuario": "boolean | 0 | 1 (opcional)",
    "agendar_sucursal": "boolean | 0 | 1 (opcional)"
  }
}
```

#### Response

**Success (200):**
```json
{
  "reply": "string - Respuesta final para el usuario",
  "session_id": "string - ID de sesion",
  "agent_used": "string | null - Agente que proceso ('reserva', 'venta', 'cita', o null)",
  "action": "string - Accion tomada ('delegate' o 'respond')"
}
```

#### Ejemplos

**Ejemplo 1: Solicitud de Reserva (Delegacion)**

Request:
```json
{
  "message": "Quiero reservar un turno para manana",
  "session_id": "user_abc123",
  "config": {
    "nombre_bot": "Asistente Spa",
    "id_empresa": 5,
    "rol_bot": "asistente",
    "tipo_bot": "reservas",
    "objetivo_principal": "ayudar a los clientes con sus reservas",
    "personalidad": "amable y profesional",
    "modalidad": "reservas de turnos"
  }
}
```

Response:
```json
{
  "reply": "Perfecto, dejame revisar la disponibilidad para manana. Que horario te conviene mejor: manana o tarde?",
  "session_id": "user_abc123",
  "agent_used": "reserva",
  "action": "delegate"
}
```

**Ejemplo 2: Saludo (Respuesta Directa)**

Request:
```json
{
  "message": "Hola",
  "session_id": "user_xyz789",
  "config": {
    "nombre_bot": "Asistente MaravIA",
    "id_empresa": 10,
    "rol_bot": "asistente",
    "tipo_bot": "general",
    "objetivo_principal": "ayudar a los clientes",
    "frase_saludo": "Hola! Soy tu asistente virtual."
  }
}
```

Response:
```json
{
  "reply": "Hola! Soy tu asistente virtual. En que puedo ayudarte hoy? Puedo ayudarte con reservas de turnos.",
  "session_id": "user_xyz789",
  "agent_used": null,
  "action": "respond"
}
```

**Ejemplo 3: Continuacion de Conversacion**

Request (despues de iniciar reserva):
```json
{
  "message": "A las 3 de la tarde",
  "session_id": "user_abc123",
  "config": {
    "nombre_bot": "Asistente Spa",
    "id_empresa": 5,
    "rol_bot": "asistente",
    "tipo_bot": "reservas",
    "objetivo_principal": "ayudar a los clientes"
  }
}
```

Response:
```json
{
  "reply": "Excelente! Tengo disponibilidad a las 3:00 PM para manana. Necesito tu nombre para confirmar la reserva.",
  "session_id": "user_abc123",
  "agent_used": "reserva",
  "action": "delegate"
}
```

#### Errores

| Codigo | Descripcion |
|--------|-------------|
| 400 | `message` vacio |
| 400 | `session_id` vacio |
| 400 | `id_empresa` <= 0 |
| 500 | Error interno (OpenAI, MCP, etc.) |

---

## Endpoints de Informacion

### GET `/`

Informacion general del servicio.

**Response:**
```json
{
  "service": "MaravIA Orquestador",
  "version": "0.2.0",
  "status": "running",
  "features": [
    "Deteccion de intencion con structured output",
    "Memoria conversacional (ultimos 10 turnos)",
    "Delegacion a agentes MCP"
  ],
  "endpoints": {
    "chat": "/api/agent/chat",
    "config": "/config",
    "health": "/health",
    "metrics": "/metrics",
    "memory_stats": "/memory/stats",
    "clear_memory": "/memory/clear/{session_id}",
    "docs": "/docs",
    "redoc": "/redoc"
  },
  "info": "Visita /docs para ver la documentacion interactiva"
}
```

### GET `/health`

Health check para balanceadores de carga y monitoreo.

**Response:**
```json
{
  "status": "ok",
  "service": "orquestador"
}
```

### GET `/config`

Configuracion actual del servicio (sin secrets).

**Response:**
```json
{
  "mcp_reserva_url": "http://localhost:8003/mcp",
  "mcp_cita_url": "http://localhost:8002/mcp",
  "mcp_venta_url": "http://localhost:8001/mcp",
  "mcp_reserva_enabled": true,
  "openai_model": "gpt-4o-mini"
}
```

---

## Endpoints de Memoria

### GET `/memory/stats`

Estadisticas de sesiones activas en memoria.

**Response:**
```json
{
  "total_sessions": 42,
  "sessions": {
    "user_abc123": 5,
    "user_xyz789": 3,
    "user_def456": 10
  }
}
```

- `total_sessions`: Numero total de sesiones activas
- `sessions`: Mapa de session_id -> cantidad de turnos almacenados

### POST `/memory/clear/{session_id}`

Limpia la memoria de una sesion especifica.

**Parametros de URL:**
- `session_id` (string, requerido): ID de la sesion a limpiar

**Response:**
```json
{
  "message": "Memoria limpiada para session_id: user_abc123"
}
```

---

## Endpoints de Monitoreo

### GET `/metrics`

Metricas de rendimiento y estado de circuit breakers.

**Response:**
```json
{
  "requests_total": 1523,
  "requests_errors": 12,
  "requests_delegate": 987,
  "requests_respond": 524,
  "latency_avg_ms": 342.5,
  "latency_p50_ms": 280.0,
  "latency_p95_ms": 650.0,
  "latency_p99_ms": 890.0,
  "circuit_breakers": {
    "reserva": {
      "state": "closed",
      "failure_count": 0
    }
  }
}
```

**Campos:**
- `requests_total`: Total de requests procesados
- `requests_errors`: Requests con error
- `requests_delegate`: Requests delegados a agentes MCP
- `requests_respond`: Requests respondidos directamente
- `latency_*`: Estadisticas de latencia en milisegundos
- `circuit_breakers`: Estado de cada circuit breaker
  - `state`: `closed` (normal), `open` (rechazando), `half_open` (probando)
  - `failure_count`: Numero de fallos consecutivos

---

## Documentacion Interactiva

### GET `/docs`

Swagger UI - Documentacion interactiva con capacidad de probar endpoints.

### GET `/redoc`

ReDoc - Documentacion alternativa en formato mas legible.

---

## Modelos de Datos

### ChatConfig

Configuracion del bot que viene en cada request.

| Campo | Tipo | Requerido | Descripcion |
|-------|------|-----------|-------------|
| `nombre_bot` | string | Si | Nombre del asistente |
| `id_empresa` | integer | Si | ID de la empresa (> 0) |
| `rol_bot` | string | Si | Rol del bot |
| `tipo_bot` | string | Si | Tipo de bot |
| `objetivo_principal` | string | Si | Objetivo del asistente |
| `frase_saludo` | string | No | Frase de saludo personalizada |
| `archivo_saludo` | string | No | Archivo de audio de saludo |
| `personalidad` | string | No | Descripcion de personalidad |
| `tono_com` | string | No | Tono de comunicacion |
| `frase_des` | string | No | Frase de despedida |
| `frase_no_sabe` | string | No | Frase cuando no sabe |
| `modalidad` | string | No | Modalidad de servicio |
| `temas_esc` | string | No | Temas para escalar |
| `frase_esc` | string | No | Frase de escalamiento |
| `motivo_der` | string | No | Motivo de derivacion |
| `motivo_so` | string | No | Motivo secundario |
| `fecha_formateada` | string | No | Fecha actual formateada |
| `fecha_iso` | string | No | Fecha en formato ISO |
| `duracion_cita_minutos` | integer | No | Duracion de citas |
| `slots` | integer | No | Slots disponibles |
| `agendar_usuario` | boolean | No | Permitir agendar usuario |
| `agendar_sucursal` | boolean | No | Permitir agendar sucursal |

### ChatRequest

Request completo al endpoint de chat.

```typescript
interface ChatRequest {
  message: string;      // Mensaje del usuario
  session_id: string;   // ID de sesion/conversacion
  config: ChatConfig;   // Configuracion del bot
}
```

### ChatResponse

Response del endpoint de chat.

```typescript
interface ChatResponse {
  reply: string;              // Respuesta al usuario
  session_id: string;         // ID de sesion
  agent_used: string | null;  // "reserva" | "venta" | "cita" | null
  action: string | null;      // "delegate" | "respond"
}
```

### OrquestradorDecision

Estructura interna de decision del orquestador (OpenAI Structured Output).

```typescript
interface OrquestradorDecision {
  action: "delegate" | "respond";
  agent_name: "reserva" | "venta" | "cita" | null;
  response: string;
}
```

---

## Codigos de Error

### HTTP Status Codes

| Codigo | Significado | Cuando ocurre |
|--------|-------------|---------------|
| 200 | OK | Request exitoso |
| 400 | Bad Request | Validacion fallida (message vacio, session_id vacio, id_empresa invalido) |
| 500 | Internal Server Error | Error en OpenAI, MCP, o procesamiento interno |

### Formato de Error

```json
{
  "detail": "Descripcion del error"
}
```

### Errores Comunes

**400 - Message vacio:**
```json
{
  "detail": "El campo 'message' no puede estar vacio"
}
```

**400 - Session ID vacio:**
```json
{
  "detail": "El campo 'session_id' no puede estar vacio"
}
```

**400 - ID Empresa invalido:**
```json
{
  "detail": "El campo 'config.id_empresa' debe ser un numero mayor a 0"
}
```

**500 - OpenAI API Key no configurada:**
```json
{
  "detail": "OPENAI_API_KEY no configurada"
}
```

**500 - Timeout en MCP:**
```json
{
  "detail": "Timeout (>30s)"
}
```

---

## Rate Limiting

Actualmente no hay rate limiting implementado. Se recomienda implementar a nivel de infraestructura (nginx, API Gateway) o agregar middleware de FastAPI.

## Autenticacion

No hay autenticacion implementada. El servicio esta disenado para ser consumido por n8n en una red interna. Para exposicion publica, agregar autenticacion via API Key o JWT.

---

## Ejemplos con cURL

### Chat basico

```bash
curl -X POST http://localhost:8000/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hola, quiero reservar",
    "session_id": "test_123",
    "config": {
      "nombre_bot": "Asistente",
      "id_empresa": 1,
      "rol_bot": "asistente",
      "tipo_bot": "reservas",
      "objetivo_principal": "ayudar"
    }
  }'
```

### Health check

```bash
curl http://localhost:8000/health
```

### Ver metricas

```bash
curl http://localhost:8000/metrics
```

### Limpiar sesion

```bash
curl -X POST http://localhost:8000/memory/clear/test_123
```

---

## Integracion con n8n

El endpoint `/api/agent/chat` esta disenado para ser llamado desde un workflow de n8n. Ejemplo de configuracion:

1. **HTTP Request Node**
   - Method: POST
   - URL: `http://orquestador:8000/api/agent/chat`
   - Body Type: JSON
   - JSON Body: Mapear campos del mensaje entrante

2. **Campos a mapear:**
   - `message`: Mensaje del usuario desde WhatsApp/Telegram/etc.
   - `session_id`: ID unico de la conversacion
   - `config`: Configuracion del bot desde base de datos

---

*Documentacion generada para MaravIA Orquestador v0.2.0*
