from fastapi import APIRouter

from app.api.v1.today import router as today_router

router = APIRouter()
router.include_router(today_router, tags=["daily"])
