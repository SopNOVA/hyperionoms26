from datetime import datetime, timedelta, timezone
from typing import Optional, Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.models.user import User

settings = get_settings()

pwd_context = CryptContext(
    schemes=["bcrypt", "sha256_crypt"],
    deprecated="auto",
    # We include sha256_crypt as fallback because some environments have
    # broken bcrypt/passlib compatibility (bcrypt 4.x + old passlib).
    # The demo user will prefer bcrypt but can fall back.
)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


# --- Dev convenience user (single definition to avoid duplication) ---
class _DevFallbackUser:
    """Synthetic user returned only in development when DEV_AUTO_AUTH is enabled.
    This object intentionally has a very small surface so that most code paths
    (role checks, id, username) continue to work without being a real SQLAlchemy model.
    """
    id = 1
    username = "tech"
    role = "technician"
    is_active = True
    full_name = "Técnico Demo"
    email = None
    hashed_password = "x"

    def __repr__(self):
        return "<_DevFallbackUser tech (auto-auth)>"


def _get_dev_fallback_user(db: Session) -> Any:
    """Try to return the real 'tech' user from DB. If not possible, return the synthetic fallback.
    Only called when DEV_AUTO_AUTH is active.
    """
    try:
        demo = db.query(User).filter(User.username == "tech").first()
        if demo and demo.is_active:
            return demo
    except Exception:
        pass
    return _DevFallbackUser()


def get_current_user(token: Optional[str] = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    """
    Resolve the current authenticated technician.

    Production behavior (ENVIRONMENT=production or DEV_AUTO_AUTH=false):
        - Strict JWT validation. Raises 401 on any problem.

    Development / test convenience (historical, for ngrok + real ONU testing):
        - If no token or invalid token, and DEV_AUTO_AUTH is enabled,
          automatically return the demo technician ("tech").
        - This eliminates constant 401s while developing the dashboard
          or testing from external networks with real ontprobe agents.
        - Real tokens (from /auth/login) always take precedence.

    Long-term recommendation:
        Set ENVIRONMENT=production and/or DEV_AUTO_AUTH=false in production .env
        and restrict CORS_ORIGINS.
    """
    dev_mode = settings.ENVIRONMENT.lower() in ("development", "test", "dev")
    auto_auth = getattr(settings, "DEV_AUTO_AUTH", True)

    if dev_mode and auto_auth:
        # No token provided → dev fallback
        if not token:
            return _get_dev_fallback_user(db)

        # Token present: try to validate it first (real login wins)
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            username: str = payload.get("sub")
            if username:
                user = db.query(User).filter(User.username == username).first()
                if user and user.is_active:
                    return user
        except Exception:
            pass

        # Token invalid or user not found → still give dev fallback (the whole point for field testing)
        return _get_dev_fallback_user(db)

    # === Strict production / disabled-auto-auth path ===
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.username == username).first()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def get_current_active_technician(current_user: User = Depends(get_current_user)) -> User:
    """Require at least technician role (or higher). For now allow all active."""
    # Support both real User.role (Enum) and the string on the dev fallback
    role_val = getattr(current_user, "role", None)
    if isinstance(role_val, str):
        role_str = role_val
    else:
        role_str = getattr(role_val, "value", str(role_val) if role_val else "")

    if role_str not in ("technician", "supervisor", "admin"):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    return current_user
