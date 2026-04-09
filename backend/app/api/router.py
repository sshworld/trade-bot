from fastapi import APIRouter

from app.api.routes import analysis, health, market, trading

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(market.router, tags=["market"])
api_router.include_router(analysis.router, tags=["analysis"])
api_router.include_router(trading.router, tags=["trading"])
