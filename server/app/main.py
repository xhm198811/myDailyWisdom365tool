"""应用入口。启动时探活数据库，失败则整体降级为内置兜底数据，不让页面开天窗。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.db.session import dispose_engine, init_engine, session_scope, set_db_available

DESCRIPTION = """
每日问候小程序后端。聚合三类信息为一个接口：

- **日期**：公历 / 农历 / 干支生肖 / 二十四节气 / 节假日与调休 / 下一个假期倒计时
- **天气**：和风天气 devapi，带两级缓存，无 key 时降级 mock
- **敬语**：Supabase 语料库按场景加权随机

小程序端只需调用 `GET /api/v1/today`。
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    if init_engine():
        try:
            async with session_scope() as s:
                if s is not None:
                    await s.execute(text("select 1"))
            print("[startup] database: connected")
        except Exception as exc:  # 连不上就降级，不影响页面
            set_db_available(False)
            print(f"[startup] database: unavailable, fallback mode ({exc.__class__.__name__})")
    else:
        print("[startup] database: not configured (no password), fallback mode")

    if not settings.QWEATHER_API_KEY:
        print("[startup] weather: no QWEATHER_API_KEY, using mock")

    yield
    await dispose_engine()


app = FastAPI(
    title=settings.APP_NAME,
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix=settings.API_PREFIX)


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "docs": "/docs",
        "api": settings.API_PREFIX,
        "endpoints": [
            f"GET {settings.API_PREFIX}/today?city=宁波",
            f"GET {settings.API_PREFIX}/greeting/random",
            f"GET {settings.API_PREFIX}/calendar?year=2026",
            f"GET {settings.API_PREFIX}/health",
        ],
    }
