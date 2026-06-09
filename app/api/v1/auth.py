from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    get_current_active_technician,
)
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserRead

router = APIRouter()


@router.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Login with username/password. Returns JWT for technicians."""
    # Special dev convenience: if using the demo credentials, ensure the user exists
    # and allow login even if the bcrypt backend is having issues in some environments.
    # This helps a lot when testing via ngrok from ONUs.
    if form_data.username == "tech" and form_data.password == "tech123":
        user = db.query(User).filter(User.username == "tech").first()
        if not user or not user.is_active:
            # create or repair on the fly. Use sha256_crypt fallback if bcrypt is broken.
            from app.core.security import get_password_hash
            from app.models.user import UserRole
            from passlib.hash import sha256_crypt
            try:
                hashed = get_password_hash("tech123")
            except Exception:
                # bcrypt broken (common with bcrypt>=4 + passlib), fall back
                hashed = sha256_crypt.hash("tech123")
            if user:
                db.delete(user)
                db.commit()
            user = User(
                username="tech",
                full_name="Técnico Demo",
                role=UserRole.TECHNICIAN,
                hashed_password=hashed,
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        # issue token directly for demo
        access_token_expires = timedelta(minutes=480)
        access_token = create_access_token(
            data={"sub": user.username, "role": user.role.value, "user_id": user.id},
            expires_delta=access_token_expires,
        )
        return {"access_token": access_token, "token_type": "bearer", "user": {
            "id": user.id, "username": user.username, "role": user.role.value, "full_name": user.full_name
        }}

    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token_expires = timedelta(minutes=480)  # 8h
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role.value, "user_id": user.id},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer", "user": {
        "id": user.id, "username": user.username, "role": user.role.value, "full_name": user.full_name
    }}


@router.post("/users", response_model=UserRead, status_code=201)
def create_technician_user(
    user_in: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_technician),
):
    """Create a new user (defaults to TECHNICIAN role). Only for internal/technical staff."""
    existing = db.query(User).filter(User.username == user_in.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")

    # Force technician or allow specified (but focus on techs)
    role = user_in.role if user_in.role else UserRole.TECHNICIAN

    db_user = User(
        username=user_in.username,
        email=user_in.email,
        full_name=user_in.full_name,
        role=role,
        hashed_password=get_password_hash(user_in.password),
        is_active=True,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.get("/me", response_model=UserRead)
def read_users_me(current_user: User = Depends(get_current_active_technician)):
    """Get current logged in technician info."""
    return current_user

