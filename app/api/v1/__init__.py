from fastapi import APIRouter

from app.api.v1 import auth, onts, customers, telemetry, olts

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(onts.router, prefix="/onts", tags=["onts"])
api_router.include_router(customers.router, prefix="/customers", tags=["customers"])
api_router.include_router(olts.router, prefix="/olts", tags=["olts"])
api_router.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
