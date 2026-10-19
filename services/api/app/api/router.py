from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.identity import router as identity_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(identity_router, prefix="/identity", tags=["identity"])
