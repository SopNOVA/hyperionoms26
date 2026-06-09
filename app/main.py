from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pathlib import Path
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from app.api.v1 import api_router
from app.core.config import get_settings
from app.services.monitor import start_monitor, shutdown_monitor
from app.core.database import SessionLocal, Base, get_db
from app.models.user import User, UserRole
from app.core.security import get_password_hash, verify_password
from app.models.ont import Ont
from app.models.telemetry import TelemetryEvent
from app.models.olt import OLT
from app.models.customer import Customer
from app.models.ping_log import PingLog
from app.services.classifier import classify_telemetry
from app.services.ingest import process_telemetry_event, parse_probe_payload

settings = get_settings()

logging.basicConfig(level=logging.INFO)


# Lifespan for background ping sensor (1 min interval) + Windows friendly
from contextlib import asynccontextmanager


def _ensure_demo_user():
    """
    Seed / repair the demo technician (tech / tech123) at startup.

    This exists purely for frictionless development and field testing with ngrok + real ONUs.
    It is aggressive on purpose in dev because bcrypt/passlib combinations have been
    fragile across environments.

    Long-term maintainability:
      - Controlled by settings.DEMO_USER_ENABLED (default True for dev).
      - In production set DEMO_USER_ENABLED=false (or ENVIRONMENT=production).
      - The repair logic (delete + recreate) is kept but only when the user is clearly broken.
    """
    if not getattr(get_settings(), "DEMO_USER_ENABLED", True):
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "tech").first()
        needs_recreate = False

        if user:
            try:
                if not verify_password("tech123", user.hashed_password):
                    needs_recreate = True
            except Exception:
                needs_recreate = True

            if not user.is_active:
                needs_recreate = True

        if needs_recreate and user:
            db.delete(user)
            db.commit()
            user = None
            logging.info("Removed old/broken demo user 'tech'")

        if not user:
            from passlib.hash import sha256_crypt
            try:
                h = get_password_hash("tech123")
            except Exception:
                h = sha256_crypt.hash("tech123")
            user = User(
                username="tech",
                full_name="Técnico Demo",
                role=UserRole.TECHNICIAN,
                hashed_password=h,
                is_active=True,
            )
            db.add(user)
            db.commit()
            logging.info("Demo technician user ensured: tech / tech123")
    except Exception as e:
        logging.warning(f"Could not ensure demo user (non-fatal): {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logging.info("Starting Hyperion-ONMS...")
    # Create tables if not migrated (safe for dev + tests)
    try:
        Base.metadata.create_all(bind=SessionLocal().bind)
    except Exception:
        pass
    _ensure_demo_user()
    start_monitor()  # 1-minute OLT ping sensor + propagation of outages
    yield
    # Shutdown
    shutdown_monitor()
    logging.info("Hyperion-ONMS shutdown complete.")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Hyperion-ONMS - Sistema de Monitoreo de Redes Ópticas (FTTH/GPON) para personal técnico",
    version=settings.VERSION,
    lifespan=lifespan,
)

# CORS - ajustar en producción
# CORS - now configurable (see config.py + .env)
_cors = get_settings().CORS_ORIGINS
if isinstance(_cors, str):
    allow_origins = [o.strip() for o in _cors.split(",")] if _cors != "*" else ["*"]
else:
    allow_origins = _cors or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Note: In production you should set a restrictive CORS_ORIGINS list in .env.

# Include all API routes
app.include_router(api_router, prefix="/api/v1")


# Serve the beautiful modern dashboard (self-contained, Tailwind + Chart.js)
DASHBOARD_PATH = Path(__file__).parent / "static" / "dashboard.html"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def dashboard():
    """Main user interface - modern dashboard for technicians."""
    if DASHBOARD_PATH.exists():
        return HTMLResponse(content=DASHBOARD_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Hyperion-ONMS</h1><p>Dashboard file missing. See /docs for API.</p>")


@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)  # no content to avoid 404 spam in logs


# Endpoint for ontprobe (and ngrok external tests from ONUs).
# This is the legacy / tolerant ingestion path used by the real C binary on the ONUs.
#
# IMPORTANT (maintainability note 2026-06):
#   All the complex tolerant parsing, auto-provisioning, customer matching,
#   config-drift detection and low-uptime heuristics now live in
#   app/services/ingest.py (process_telemetry_event + parse_probe_payload).
#
#   This handler is intentionally kept thin: it only deals with
#   "accept any shape of request" and then delegates.
@app.post("/ont-monitor", include_in_schema=False)
async def ont_monitor_test(request: Request):
    """Legacy entry point used by ontprobe from real ONUs (via ngrok or direct)."""
    logger = logging.getLogger("hyperion")

    # Be extremely tolerant — real probes in the field send many shapes.
    try:
        payload = await request.json()
    except Exception:
        try:
            body = await request.body()
            payload = {"raw": body.decode("utf-8", errors="replace")[:2000]}
        except Exception:
            payload = {"raw": "unparseable body"}

    logger.info(f"ontprobe data received at /ont-monitor: {str(payload)[:600]}")

    db = next(get_db())
    try:
        # Safety net: tables may not exist yet on first hit after reload
        try:
            Base.metadata.create_all(bind=db.bind)
        except Exception:
            pass

        # Delegate everything to the maintainable service layer.
        # This unifies behavior with the structured /api/v1/telemetry/ingest path.
        result = process_telemetry_event(db, payload, delivery="ontprobe")

        return {
            "status": "accepted",
            "message": "✅ ontprobe data received and stored successfully",
            "ont_id": result["ont_id"],
            "gpon_sn": result["gpon_sn"],
            "classification": result["classification"],
            "reason": result["reason"],
            "event_id": result["event_id"],
            "olt_status": result.get("olt_status"),
            "note": "Data is now visible in the Hyperion-ONMS dashboard (click the client/ONT)",
        }

    except Exception as e:
        db.rollback()
        logger.exception("Error processing ontprobe data at /ont-monitor")
        return {
            "status": "error",
            "message": f"Error processing data: {str(e)}",
            "raw_payload": str(payload)[:1000],
        }
    finally:
        db.close()


# Also support GET for quick browser/curl checks from ngrok or the ONU side
@app.get("/ont-monitor", include_in_schema=False)
async def ont_monitor_test_get():
    return {
        "status": "ok",
        "message": "Hyperion-ONMS reachable from external (ngrok). POST your ontprobe data here.",
        "real_ingest": "/api/v1/telemetry/ingest (preferred for full classification)",
        "dashboard": "Open the ngrok URL in browser to see live data",
        "health": "/health",
        "tip": "Run your probe like: LD_LIBRARY_PATH=... /etc/scripts/ontprobe <your-ngrok>/ont-monitor 300 300 AUTO"
    }


# (lifespan already defined above before FastAPI app instantiation)


# (lifespan already passed to FastAPI constructor above)
