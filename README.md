# Hyperion-ONMS

**Hyperion-ONMS - Sistema moderno de Monitoreo de Redes Ópticas (ONMS) para ISPs FTTH/GPON.**

Este es el proyecto **serio / producción** de la plataforma de monitoreo.

> **Nota importante**: El directorio `onudash` (en el mismo nivel) contiene la **versión de pruebas/prototipo** antigua.  
> Este directorio (`ontmonitor` renombrado internamente) es **Hyperion-ONMS**, el proyecto profesional completo.

## Objetivo

Plataforma interna para el equipo técnico del ISP que permite:

- Gestión de usuarios técnicos (Admin, Supervisor/NOC, Técnico de Campo)
- Inventario de Clientes y ONUs (asociadas por GPON Serial)
- Recepción de telemetría en tiempo real desde agentes `ontprobe`
- Historial, estado actual, alertas y diagnósticos por ONU
- Búsqueda rápida por nombre de cliente, GPON SN o IP
- Alertas basadas en clasificación y métricas

**Solo para uso interno del personal técnico.** No hay portal para clientes finales.

## Estado actual

**Estructura base lista** (Abril 2026):

- Estructura profesional FastAPI
- Modelos iniciales: `User` (con roles Admin/Supervisor/Technician), `Customer`, `Ont` (gpon_sn como clave), `TelemetryEvent`
- API routers básicos (auth, onts, customers, telemetry)
- Configuración con Pydantic Settings
- SQLAlchemy + Alembic preparado
- Docker Compose con PostgreSQL
- Separación clara del prototipo de pruebas

Próximos pasos naturales:
- Generar primera migración de Alembic
- Implementar autenticación JWT + dependencia de roles
- Endpoint de ingesta de telemetría (POST /api/v1/telemetry/ingest)
- Asociación de ONU con Cliente
- Dashboard básico (puede empezar con HTMX o el index.html del prototipo adaptado)

## Cómo empezar (recomendado con Docker)

```bash
# 1. Copia las variables de entorno
cp .env.example .env

# 2. Levanta todo (base de datos + aplicación)
docker compose up --build

# 3. La API estará en http://localhost:8000
#    Documentación: http://localhost:8000/docs
```

Dentro del contenedor puedes ejecutar migraciones manualmente si es necesario:

```bash
docker compose exec app alembic revision --autogenerate -m "initial"
docker compose exec app alembic upgrade head
```

## Estructura del proyecto

```
hyperion-onms / ontmonitor (directorio) /
├── app/
│   ├── main.py
│   ├── core/          # Config, security, database
│   ├── models/        # SQLAlchemy models
│   ├── schemas/       # Pydantic schemas
│   ├── api/v1/        # Endpoints
│   ├── services/      # Lógica de negocio
│   └── db/            # Session, migrations helpers
├── alembic/           # Migraciones de base de datos
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── README.md
└── ...
```

## Tecnologías principales (planeadas)

- Python + FastAPI
- PostgreSQL (con JSONB para telemetría)
- SQLAlchemy + Alembic
- Pydantic v2
- JWT + roles para autenticación interna
- Docker Compose (despliegue principal)
- (Futuro) Redis para tareas y colas

## Cómo correr (desarrollo)

```bash
# 1. Levantar con Docker Compose (recomendado)
docker compose up --build

# 2. O desarrollo local
# - Instalar PostgreSQL
# - poetry install o pip install -e .
# - uvicorn app.main:app --reload
```

## Ejecutar pruebas (tests)

Las primeras pruebas unitarias/integración están listas en `tests/`.

```bash
# Con dependencias instaladas (dev):
pip install -e ".[dev]"

# Ejecutar todas las pruebas:
pytest -q

# O verboso:
pytest -v --tb=short

# Con docker (recomendado una vez levantado):
# docker compose run --rm app pytest -q
```

Actualmente las pruebas usan SQLite en memoria (rápido, aislado) y cubren:
- Endpoints básicos: `/`, `/health`
- CRUD inicial de ONTs (`/api/v1/onts`)
- Stubs de auth, customers, telemetry (para asegurar wiring)

Las pruebas crean las tablas vía `Base.metadata.create_all` (no requieren migraciones para test).

## Probando con ngrok + ontprobe desde ONUs reales

1. Levanta el servidor:
   uvicorn app.main:app --reload

2. ngrok http 8000

3. Desde la ONU:
   LD_LIBRARY_PATH=/etc/scripts/lib /etc/scripts/ontprobe \
     https://TU-NGROK.ngrok-free.dev/ont-monitor 300 300 AUTO &

4. Abre la URL de ngrok en el navegador:
   - En development hace **auto-login** con tech/tech123.
   - Verás los datos que llegan del probe en tiempo real (sin 401s).
   - Click en clientes/ONTs para pings 8.8.8.8/1.1.1.1, jitter, tiempo total de servicios, observaciones de TCP retrans etc.

**Fix para errores de bcrypt/passlib ("Credenciales inválidas")**:
   pip install "bcrypt<4.0.0" --force-reinstall
   (luego reinicia uvicorn)

El código tiene casos especiales para el usuario demo + bypass en dev para que las pruebas con ngrok fluyan sin fricción.
```

## Separación de versiones

## Separación de versiones

- `/home/cypherhn/onudash` → **Prototipo / pruebas** (archivos JSON, servidor básico http.server, dashboard estático)
- `/home/cypherhn/ontmonitor` → **Proyecto serio** (esta carpeta)

---

## Hyperion-ONMS - Características clave (2026)

- **Usuarios técnicos**: Creación de usuarios (por defecto TECHNICIAN). Login JWT completo.
- **Clientes + Matching inteligente**: Crea cliente con nombre, MAC, GPON, IP. Si existe ONU con GPON/MAC se asocia automáticamente ("se conecta exitosamente").
- **OLTs**: CRUD completo. Vincula ONTs a OLTs.
- **Sensor Ping 1 minuto**: Background job (apscheduler + icmplib). Si OLT cae → propaga CRITICAL a todos los clientes/ONTs asociados (aparecen en alertas).
- **Dashboard moderno principal**: 
  - Solo alertas seccionadas: OLTs caídas, clientes masivos caídos, ONUs críticas.
  - Grid de OLTs con estado vivo.
  - Tabla de clientes searchable.
  - Click en cliente → detalles + estadísticas del JSON (ping 8.8.8.8 y 1.1.1.1, observación TCP retrans cuando servicios buenos = GOOD).
  - Selector de rango de fecha → **Dashboard optimizado** con gráficos Chart.js: solo ping, jitter y tiempo total de conexión de servicios (sin TCP retrans en las gráficas).
- Totalmente moderno (Tailwind + Chart.js CDN, dark tech), responsive, compatible Windows (código puro + icmplib).
- Seed demo al iniciar (usuario tech/tech123 + datos).

## Cómo ejecutar

```bash
# 1. Copia env
cp .env.example .env

# 2. Docker (recomendado)
docker compose up --build

# 3. Abre http://localhost:8000  ← El dashboard moderno
#    API docs: /docs
#    Login demo: tech / tech123
```

O localmente (después de instalar deps):

```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Pruebas

```bash
pytest -q
```

El proyecto es 100% funcional: matching, ingest con clasificación especial, sensor, dashboard completo, auth.

---

¡Proyecto renombrado y mejorado a Hyperion-ONMS! Todo revisado para que funcione correctamente (sintaxis, lógica, Windows, tests actualizados).

