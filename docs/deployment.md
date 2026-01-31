# Guia de Deployment - MaravIA Orquestador

Guia completa para desplegar el Orquestador en diferentes entornos.

---

## Tabla de Contenidos

1. [Requisitos Previos](#requisitos-previos)
2. [Configuracion de Entorno](#configuracion-de-entorno)
3. [Deployment Local](#deployment-local)
4. [Deployment con Docker](#deployment-con-docker)
5. [Deployment en Produccion](#deployment-en-produccion)
6. [Variables de Entorno](#variables-de-entorno)
7. [Verificacion Post-Deployment](#verificacion-post-deployment)
8. [Monitoreo y Logging](#monitoreo-y-logging)
9. [Troubleshooting](#troubleshooting)
10. [Seguridad](#seguridad)
11. [Escalamiento](#escalamiento)
12. [Backup y Recuperacion](#backup-y-recuperacion)

---

## Requisitos Previos

### Software

| Software | Version Minima | Proposito |
|----------|----------------|-----------|
| Python | 3.12+ | Runtime |
| pip | 23.0+ | Gestor de paquetes |
| Docker | 24.0+ | Containerizacion |
| Docker Compose | 2.0+ | Orquestacion local |

### Recursos

| Recurso | Minimo | Recomendado |
|---------|--------|-------------|
| CPU | 1 core | 2 cores |
| RAM | 512 MB | 1 GB |
| Disco | 500 MB | 1 GB |

### Dependencias Externas

- **OpenAI API Key**: Requerido para el modelo orquestador
- **Agentes MCP**: Opcionales, segun funcionalidad requerida
- **API Contexto de Negocio**: Opcional, para informacion de empresa

---

## Configuracion de Entorno

### 1. Crear archivo .env

```bash
cp .env.example .env
```

### 2. Configurar variables requeridas

```env
# REQUERIDO: OpenAI
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_MODEL=gpt-4o-mini

# OPCIONAL: Agentes MCP
MCP_RESERVA_URL=http://localhost:8003/mcp
MCP_RESERVA_ENABLED=true

# OPCIONAL: Contexto de negocio
CONTEXTO_NEGOCIO_ENDPOINT=https://api.maravia.pe/servicio/ws_informacion_ia.php
```

### 3. Verificar permisos

```bash
# El archivo .env no debe ser accesible publicamente
chmod 600 .env
```

---

## Deployment Local

### Opcion A: Ejecucion Directa

```bash
# 1. Crear entorno virtual
python -m venv venv

# 2. Activar entorno
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Ejecutar
python src/orquestador/main.py
```

El servidor estara disponible en `http://localhost:8000`

### Opcion B: Con uvicorn directamente

```bash
# Desarrollo (con reload)
uvicorn src.orquestador.main:app --reload --host 0.0.0.0 --port 8000

# Produccion (sin reload, multiples workers)
uvicorn src.orquestador.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## Deployment con Docker

### Construccion de Imagen

```bash
# Construir imagen
docker build -t maravia-orquestador:latest .

# Verificar imagen
docker images | grep maravia-orquestador
```

### Ejecucion con Docker

```bash
# Ejecutar contenedor
docker run -d \
  --name orquestador \
  -p 8000:8000 \
  --env-file .env \
  --restart unless-stopped \
  maravia-orquestador:latest

# Verificar logs
docker logs -f orquestador
```

### Ejecucion con Docker Compose

```bash
# Iniciar servicio
docker-compose up -d

# Ver logs
docker-compose logs -f

# Detener
docker-compose down
```

### Dockerfile Detallado

```dockerfile
# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

# Evitar bytecode y buffering
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Usuario no privilegiado (seguridad)
ARG UID=10001
RUN adduser \
    --disabled-password \
    --gecos "" \
    --home "/nonexistent" \
    --shell "/sbin/nologin" \
    --no-create-home \
    --uid "${UID}" \
    appuser

# Dependencias (cache optimizado)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# Cambiar a usuario no privilegiado
USER appuser

# Codigo de aplicacion
COPY src ./src

EXPOSE 8000

CMD ["uvicorn", "src.orquestador.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### compose.yaml

```yaml
services:
  orquestador:
    build:
      context: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

---

## Deployment en Produccion

### Arquitectura Recomendada

```
                     ┌─────────────┐
                     │   nginx     │
                     │ (reverse    │
                     │  proxy)     │
                     └──────┬──────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │Orquestador│  │Orquestador│  │Orquestador│
        │ Instance 1│  │ Instance 2│  │ Instance 3│
        └──────────┘  └──────────┘  └──────────┘
              │             │             │
              └─────────────┼─────────────┘
                            │
                     ┌──────┴──────┐
                     │    Redis    │
                     │  (memoria)  │
                     └─────────────┘
```

### Paso 1: Preparar Servidor

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Instalar Docker Compose
sudo apt install docker-compose-plugin
```

### Paso 2: Clonar y Configurar

```bash
# Clonar repositorio
git clone <repo-url> /opt/maravia/orquestador
cd /opt/maravia/orquestador

# Configurar entorno
cp .env.example .env
nano .env  # Editar con valores de produccion
chmod 600 .env
```

### Paso 3: Construir y Ejecutar

```bash
# Construir imagen
docker-compose build

# Ejecutar en background
docker-compose up -d

# Verificar estado
docker-compose ps
docker-compose logs
```

### Paso 4: Configurar Nginx (Reverse Proxy)

```nginx
# /etc/nginx/sites-available/orquestador
upstream orquestador {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name api.tudominio.com;

    location / {
        proxy_pass http://orquestador;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Connection "";
        proxy_connect_timeout 60s;
        proxy_read_timeout 120s;
    }

    location /health {
        proxy_pass http://orquestador/health;
        access_log off;
    }
}
```

### Paso 5: SSL con Let's Encrypt

```bash
# Instalar certbot
sudo apt install certbot python3-certbot-nginx

# Obtener certificado
sudo certbot --nginx -d api.tudominio.com

# Renovacion automatica
sudo systemctl enable certbot.timer
```

### Paso 6: Systemd Service (alternativa a Docker)

```ini
# /etc/systemd/system/orquestador.service
[Unit]
Description=MaravIA Orquestador
After=network.target

[Service]
Type=exec
User=maravia
Group=maravia
WorkingDirectory=/opt/maravia/orquestador
Environment="PATH=/opt/maravia/orquestador/venv/bin"
EnvironmentFile=/opt/maravia/orquestador/.env
ExecStart=/opt/maravia/orquestador/venv/bin/uvicorn \
    src.orquestador.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Habilitar servicio
sudo systemctl daemon-reload
sudo systemctl enable orquestador
sudo systemctl start orquestador
sudo systemctl status orquestador
```

---

## Variables de Entorno

### Completa Referencia

```env
# ============================================
# OPENAI CONFIGURATION
# ============================================

# API Key de OpenAI (REQUERIDO)
OPENAI_API_KEY=sk-proj-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Modelo a usar (default: gpt-4o-mini)
# Opciones: gpt-4o-mini, gpt-4o, gpt-4-turbo
OPENAI_MODEL=gpt-4o-mini

# Timeout para llamadas a OpenAI en segundos (default: 60)
OPENAI_TIMEOUT=60

# ============================================
# MCP AGENTS CONFIGURATION
# ============================================

# URLs de agentes MCP
MCP_RESERVA_URL=http://localhost:8003/mcp
MCP_CITA_URL=http://localhost:8002/mcp
MCP_VENTA_URL=http://localhost:8001/mcp

# Habilitar/deshabilitar agente Reserva (default: true)
MCP_RESERVA_ENABLED=true

# Timeout para llamadas MCP en segundos (default: 30)
MCP_TIMEOUT=30

# Numero maximo de reintentos (default: 3)
MCP_MAX_RETRIES=3

# ============================================
# CIRCUIT BREAKER CONFIGURATION
# ============================================

# Numero de fallos antes de abrir el circuit (default: 5)
MCP_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5

# Tiempo en segundos antes de probar recuperacion (default: 60)
MCP_CIRCUIT_BREAKER_RESET_TIMEOUT=60

# ============================================
# CONTEXTO DE NEGOCIO
# ============================================

# Endpoint para obtener informacion de la empresa
CONTEXTO_NEGOCIO_ENDPOINT=https://api.maravia.pe/servicio/ws_informacion_ia.php

# Timeout para esta llamada en segundos (default: 10)
CONTEXTO_NEGOCIO_TIMEOUT=10
```

### Variables por Entorno

| Variable | Desarrollo | Produccion |
|----------|------------|------------|
| `OPENAI_MODEL` | gpt-4o-mini | gpt-4o-mini |
| `MCP_RESERVA_URL` | localhost:8003 | reserva:8003 |
| `MCP_TIMEOUT` | 30 | 30 |
| `LOG_LEVEL` | DEBUG | INFO |

---

## Verificacion Post-Deployment

### Checklist de Verificacion

```bash
# 1. Health check
curl http://localhost:8000/health
# Esperado: {"status":"ok","service":"orquestador"}

# 2. Info del servicio
curl http://localhost:8000/
# Esperado: JSON con version y endpoints

# 3. Configuracion
curl http://localhost:8000/config
# Esperado: URLs MCP y modelo configurado

# 4. Metricas
curl http://localhost:8000/metrics
# Esperado: Contadores y latencias

# 5. Test de chat
curl -X POST http://localhost:8000/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hola",
    "session_id": "test_deploy",
    "config": {
      "nombre_bot": "Test",
      "id_empresa": 1,
      "rol_bot": "test",
      "tipo_bot": "test",
      "objetivo_principal": "test"
    }
  }'
# Esperado: JSON con reply
```

### Script de Verificacion Automatica

```bash
#!/bin/bash
# verify_deployment.sh

BASE_URL="${1:-http://localhost:8000}"

echo "Verificando deployment en $BASE_URL..."

# Health check
if curl -sf "$BASE_URL/health" > /dev/null; then
    echo "[OK] Health check"
else
    echo "[FAIL] Health check"
    exit 1
fi

# Config
if curl -sf "$BASE_URL/config" | grep -q "openai_model"; then
    echo "[OK] Config endpoint"
else
    echo "[FAIL] Config endpoint"
    exit 1
fi

# Chat test
RESPONSE=$(curl -sf -X POST "$BASE_URL/api/agent/chat" \
    -H "Content-Type: application/json" \
    -d '{"message":"test","session_id":"verify","config":{"nombre_bot":"t","id_empresa":1,"rol_bot":"t","tipo_bot":"t","objetivo_principal":"t"}}')

if echo "$RESPONSE" | grep -q "reply"; then
    echo "[OK] Chat endpoint"
else
    echo "[FAIL] Chat endpoint"
    exit 1
fi

echo "Deployment verificado exitosamente!"
```

---

## Monitoreo y Logging

### Logs Estructurados (JSON)

Los logs se emiten en formato JSON para facil integracion:

```json
{
  "timestamp": "2025-01-30T15:30:00.123456+00:00",
  "level": "INFO",
  "logger": "orquestador.main",
  "message": "POST /api/agent/chat request",
  "extra_fields": {
    "session_id": "user_123",
    "agent_to_invoke": "reserva"
  }
}
```

### Integracion con ELK Stack

```yaml
# filebeat.yml
filebeat.inputs:
  - type: container
    paths:
      - '/var/lib/docker/containers/*/*.log'
    processors:
      - decode_json_fields:
          fields: ["message"]
          target: "json"

output.elasticsearch:
  hosts: ["elasticsearch:9200"]
```

### Integracion con CloudWatch (AWS)

```yaml
# docker-compose.yml con awslogs
services:
  orquestador:
    logging:
      driver: awslogs
      options:
        awslogs-group: "/ecs/maravia-orquestador"
        awslogs-region: "us-east-1"
        awslogs-stream-prefix: "orquestador"
```

### Alertas Basicas

Configurar alertas para:

| Metrica | Umbral | Accion |
|---------|--------|--------|
| Error rate | > 5% | Alerta |
| Latencia p95 | > 5s | Alerta |
| Circuit Open | Cualquiera | Alerta critica |
| Memory usage | > 80% | Alerta |

---

## Troubleshooting

### Problema: OpenAI API Key invalida

```
Error: OPENAI_API_KEY no configurada
```

**Solucion:**
```bash
# Verificar que existe en .env
grep OPENAI_API_KEY .env

# Verificar que Docker carga el env
docker exec orquestador env | grep OPENAI
```

### Problema: No conecta a MCP

```
Error: Timeout (>30s)
```

**Solucion:**
```bash
# Verificar que el agente MCP esta corriendo
curl http://localhost:8003/health

# Verificar conectividad desde el contenedor
docker exec orquestador curl http://host.docker.internal:8003/health
```

### Problema: Memory crece indefinidamente

**Causa:** Sesiones sin TTL acumulandose.

**Solucion temporal:**
```bash
# Limpiar sesiones manualmente
curl -X POST http://localhost:8000/memory/clear/session_antigua
```

**Solucion permanente:** Migrar a Redis con TTL.

### Problema: Circuit Breaker siempre abierto

```bash
# Ver estado
curl http://localhost:8000/metrics | jq '.circuit_breakers'
```

**Solucion:**
```bash
# Reiniciar servicio (resetea circuit breakers)
docker-compose restart
```

### Logs Utiles

```bash
# Ver logs en tiempo real
docker-compose logs -f --tail=100

# Filtrar por errores
docker-compose logs | grep '"level":"ERROR"'

# Filtrar por sesion
docker-compose logs | grep "session_123"
```

---

## Seguridad

### Checklist de Seguridad

- [ ] API Key de OpenAI no en codigo fuente
- [ ] Archivo .env con permisos 600
- [ ] Contenedor ejecuta como usuario no-root (UID 10001)
- [ ] CORS configurado para dominios especificos en produccion
- [ ] HTTPS habilitado (via nginx)
- [ ] Rate limiting configurado
- [ ] Logs no contienen datos sensibles

### Configurar CORS para Produccion

```python
# En main.py, cambiar:
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.maravia.pe", "https://admin.maravia.pe"],
    allow_credentials=True,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)
```

### Rate Limiting con nginx

```nginx
# En nginx.conf
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

server {
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://orquestador;
    }
}
```

---

## Escalamiento

### Horizontal (Multiples Instancias)

```yaml
# docker-compose.scale.yml
services:
  orquestador:
    deploy:
      replicas: 3
    # Requiere: memoria compartida (Redis)
```

**Nota:** La memoria in-memory actual NO es compartida entre instancias. Para escalar horizontalmente, migrar a Redis.

### Vertical (Mas Workers)

```bash
uvicorn src.orquestador.main:app --workers 4
```

**Recomendacion:** workers = (2 * CPU cores) + 1

### Consideraciones

| Aspecto | Estado Actual | Para Escalar |
|---------|---------------|--------------|
| Memoria | In-memory | Redis |
| Session affinity | No requerida | No requerida (con Redis) |
| Stateless | Parcial | Total (con Redis) |

---

## Backup y Recuperacion

### Backup de Configuracion

```bash
# Backup de .env y config
tar -czf backup_config_$(date +%Y%m%d).tar.gz .env compose.yaml
```

### Backup de Memoria (si migras a Redis)

```bash
redis-cli BGSAVE
cp /var/lib/redis/dump.rdb backup_redis_$(date +%Y%m%d).rdb
```

### Rollback de Deployment

```bash
# Si usas tags de version
docker-compose down
docker pull maravia-orquestador:v0.1.0  # version anterior
docker-compose up -d
```

### Disaster Recovery

1. Tener imagen Docker en registry (DockerHub, ECR)
2. Backup de .env en ubicacion segura
3. Documentar procedimiento de restauracion
4. Probar restauracion periodicamente

---

## Comandos Utiles

```bash
# Ver estado de contenedores
docker-compose ps

# Ver logs en tiempo real
docker-compose logs -f

# Reiniciar servicio
docker-compose restart

# Actualizar imagen y reiniciar
docker-compose pull && docker-compose up -d

# Entrar al contenedor
docker exec -it orquestador /bin/bash

# Ver uso de recursos
docker stats orquestador

# Limpiar imagenes antiguas
docker image prune -a
```

---

*Guia de deployment para MaravIA Orquestador v0.2.0*
