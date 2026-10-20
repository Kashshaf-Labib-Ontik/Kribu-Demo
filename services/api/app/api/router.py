from fastapi import APIRouter

from app.api.routes.demo import router as demo_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.identity import router as identity_router
from app.api.routes.retrieval import router as retrieval_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(identity_router, prefix="/identity", tags=["identity"])
api_router.include_router(demo_router, prefix="/demo", tags=["demo"])
api_router.include_router(documents_router, prefix="/documents", tags=["documents"])
api_router.include_router(retrieval_router, prefix="/retrieval", tags=["retrieval"])
