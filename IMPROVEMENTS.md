# Hyperion-ONMS — Maintainability & Hardening Pass (June 2026)

This document records the detailed analysis of "development speed" artifacts and the concrete improvements made for long-term maintainability and security hygiene.

**Backup taken before any changes**:
- `backups/hyperion-onms-full-backup-20260606-152131.tar.gz`
- `backups/hyperion-onms-full-backup-20260606-152131-dir/`

---

## 1. High-level problems observed (pre-refactor)

### 1.1 Security & "Dev Ergonomics" that leaked into the design
- `app/core/security.py:get_current_user` contained ~50 lines of auto-auth logic that returned a real DB user or a synthetic `FakeUser` when running in development/test/dev environments.
- Multiple almost-identical `class FakeUser:` definitions (duplication).
- `app/main.py:_ensure_demo_user` was extremely aggressive:
  - Deleted + recreated the `tech` user if password verification failed.
  - Had a raw SQL `INSERT OR REPLACE` fallback.
  - Ran on every startup unconditionally.
- `app/api/v1/auth.py` had its own special-case repair logic for the demo user.
- Hard-coded `allow_origins=["*"]` in FastAPI CORS middleware (with a TODO comment).
- The legacy probe endpoint `POST /ont-monitor` had no authentication at all (by design for the C agent).
- Result: very easy to accidentally run with wide-open behavior in production.

### 1.2 Concentrated / God-function code (maintenance nightmare)
- The entire `ont_monitor_test` handler in `app/main.py` (approx. 270 lines) did:
  - Request body tolerance (JSON or raw)
  - 15+ different key names for gpon_sn / mac / ip / pings
  - Auto create/find Ont
  - Customer linking
  - Classification (with fallback)
  - Config drift detection
  - Low-uptime downgrade
  - TelemetryEvent creation + last_seen updates
  - OLT touch
- Almost identical parsing logic existed in `telemetry.py:ingest_telemetry` and in the dashboard JS.

### 1.3 Duplication
- `classify_telemetry` was defined in `telemetry.py` but also imported/called from `main.py`.
- Payload shape normalization repeated in multiple places (server + several versions of the dashboard HTML).
- Time formatting (Honduras UTC-6) hard-coded in many JS locations and had a copy inside the dynamic graph popup generator.
- Manual relationship loading (`c.onts = db.query(...)`) repeated in customers.py, onts.py, etc. (comment even said "no joinedload for brevity").
- `_DevFallbackUser` / FakeUser logic duplicated.

### 1.4 Dashboard technical debt
- 1761-line single file (acceptable for zero-asset deployment, painful for evolution).
- Complex string-constructed HTML + script injection for the "open graph in new tab" feature.
- Many `.broken`, `.fixed`, `.working` copies of the dashboard left in `app/static/`.
- Heavy inline template literals and magic numbers.
- Auto-demo-login code and "dev bypass" comments scattered in the UI.

### 1.5 Other observations
- Alembic migration hard-codes `postgresql.JSON`.
- Scheduler is a global singleton (harder to test).
- No clear separation between "public unauthenticated probe ingestion" and internal authenticated API.
- Tests rely on heavy app monkey-patching.
- Several places had broad `except Exception` that could hide real problems.

---

## 2. Concrete changes made (post-refactor)

### 2.1 Configuration & explicit flags (config.py)
- Added:
  - `DEV_AUTO_AUTH: bool = True`
  - `CORS_ORIGINS: str | list[str] = "*"`
  - `DEMO_USER_ENABLED: bool = True`
- These give operators a clear, documented way to harden a deployment without code changes.

### 2.2 Security cleanup (security.py)
- Single definition of the dev fallback user (`_DevFallbackUser`).
- Extracted helper `_get_dev_fallback_user(db)`.
- `get_current_user` now has a large, honest docstring explaining the historical reason for the bypass and exactly how to disable it.
- `get_current_active_technician` now handles both real Enum roles and the string role on the synthetic user.
- Behavior is now driven by `DEV_AUTO_AUTH` (in addition to ENVIRONMENT).

### 2.3 Demo user seeder (main.py)
- `_ensure_demo_user` now respects `settings.DEMO_USER_ENABLED`.
- Removed the raw SQL hammer from the normal path (kept only as last-resort logging).
- Added clear comments about when to disable it.

### 2.4 CORS (main.py)
- Now reads from `settings.CORS_ORIGINS` and normalizes comma-separated strings.
- Old hard-coded `["*"]` + TODO removed.

### 2.5 Centralized classification (new file: app/services/classifier.py)
- Moved the full `classify_telemetry` logic (including conntrack signals, services-good override, etc.) into one place.
- Updated `telemetry.py` to import from it (re-export kept for back-compat).
- `main.py` import updated.

### 2.6 Extracted ingestion service (new file: app/services/ingest.py)
- `parse_probe_payload()` — tolerant normalizer for all the crazy key variants the real C agent sends.
- `process_telemetry_event(db, payload, delivery=...)` — the complete business pipeline:
  - find/create Ont
  - customer linking
  - classification (via the central classifier)
  - config-drift + low-uptime heuristics
  - TelemetryEvent creation + last_seen propagation
- Both `POST /ont-monitor` (legacy) and `POST /api/v1/telemetry/ingest` now delegate to this function.
- The giant handler in `main.py` was reduced to ~40 lines of "be tolerant with the HTTP request" + delegation + error wrapping.

### 2.7 Unified ingest paths
- The two historical ingestion routes now share the same core logic. Behavior is consistent and future changes only need to be made in one place.

### 2.8 Dashboard maintainability (app/static/dashboard.html)
- Added a large "MAINTAINABILITY NOTE" block at the top of the script explaining the history and future direction.
- Introduced `HONDURAS_UTC_OFFSET_HOURS` constant (single place to change the display offset).
- Updated `formatTs` to use the constant.
- Added section grouping comments.
- Kept the file as a single self-contained asset (current deployment requirement) while making it easier to navigate and evolve.

### 2.9 Other cleanups
- Updated imports and a few comments.
- The old broken/working dashboard copies were left in place (they are historical artifacts from development; the active one is `dashboard.html`).

---

## 3. Remaining recommended work (not done in this pass)

- Consider a simple shared-secret or mTLS for the probe ingestion path in production (currently intentionally open for the C agent).
- Extract the dashboard into multiple static files once you have a proper static serving story.
- Add a couple of `selectinload` / `joinedload` in the list endpoints (or use a proper query layer) to reduce the manual relationship loading.
- Make the APScheduler job injectable / easier to test in isolation.
- Improve Alembic migration to be more dialect-agnostic (use `sa.JSON()` instead of the postgresql-specific one for the initial migration if you ever need to support pure SQLite in prod).
- Add basic rate limiting / request size limits on the public ingestion endpoints.
- Expand tests to cover the new `ingest.py` and `classifier.py` directly.
- Remove or archive the old `dashboard.html.*` variants.

---

## 4. How to harden a production deployment (quick checklist)

1. `.env` (or compose env):
   ```
   ENVIRONMENT=production
   DEV_AUTO_AUTH=false
   DEMO_USER_ENABLED=false
   SECRET_KEY=<long-random>
   CORS_ORIGINS=https://your-dashboard.example.com
   ```
2. Restrict the probe ingestion if possible (network level, WAF, or add a simple `X-Probe-Token` check later).
3. Run behind a reverse proxy with TLS.
4. Use the real PostgreSQL (the compose file already does this).
5. Consider moving the dashboard behind the same auth story or at least IP allow-listing if it stays public.

---

## 5. Summary of the spirit of the changes

The original "development velocity" trade-offs were reasonable while the team was proving the concept with real ONUs in the field. The June 2026 pass makes the cost of those trade-offs explicit in code and configuration, extracts the complex business logic into testable, single-responsibility modules, and gives future maintainers clear levers instead of having to hunt for magic `if ENVIRONMENT == "development"` blocks.

The system remains fully functional for both rapid dev/ngrok testing and hardened production use.

— Generated during the maintainability refactor.
