"""今日聚合接口：一次请求拿齐日期、天气、敬语。

小程序端只需要调这一个接口，减少往返、也便于后端做缓存与降级。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Query

from app.core.config import settings
from app.db.session import db_available
from app.services import calendar_cn as cal
from app.services.greeting import pick_greeting
from app.services.holiday import get_day_info
from app.services.weather import get_weather

router = APIRouter()
CST = timezone(timedelta(hours=8))


@router.get("/health")
async def health():
    return {
        "ok": True,
        "env": settings.APP_ENV,
        "database": "up" if db_available() else "down",
        "weather": "qweather" if settings.QWEATHER_API_KEY else "mock",
    }


@router.get("/today")
async def today(
    city: str | None = Query(None, description="城市名，默认取配置 DEFAULT_CITY"),
    lat: float | None = Query(None, description="纬度，传经纬度可跳过城市查询"),
    lon: float | None = Query(None, description="经度"),
    d: str | None = Query(None, description="指定日期 YYYY-MM-DD，默认今天，便于联调"),
    tone: str = Query("classic", description="问候语气：classic 典雅 / warm 亲切 / zen 禅意"),
):
    target: date = (
        datetime.strptime(d, "%Y-%m-%d").date() if d else datetime.now(CST).date()
    )

    day_info = await get_day_info(target)
    lunar = cal.solar_to_lunar(target)
    day_info["lunar"] = lunar
    day_info["ganzhi_day"] = cal.ganzhi_of_day(target)
    day_info["next_solar_term"] = cal.next_solar_term(target)
    day_info["solar"] = {
        "year": target.year,
        "month": target.month,
        "day": target.day,
    }

    weather = await get_weather(city, lat, lon, target)
    greeting = await pick_greeting(day_info, weather)

    degraded = []
    if not db_available():
        degraded.append("database")
    if weather.get("source") == "mock":
        degraded.append("weather")

    return {
        "ok": True,
        "data": {
            "date": day_info,
            "weather": weather,
            "greeting": greeting,
            "tone": tone,
        },
        "degraded": degraded,
        "generated_at": datetime.now(CST).isoformat(),
    }


@router.get("/greeting/random")
async def greeting_random(
    city: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
):
    """换一句：命中同一套场景规则，但不复用缓存的问候。"""
    target = datetime.now(CST).date()
    day_info = await get_day_info(target)
    weather = await get_weather(city, lat, lon, target)
    return {"ok": True, "data": await pick_greeting(day_info, weather)}


@router.get("/calendar")
async def calendar(year: int = Query(..., ge=1900, le=2100)):
    """某年全部节气，便于前端做全年日历视图。"""
    terms = [
        {"name": n, "datetime": dt.isoformat(), "date": dt.date().isoformat()}
        for n, dt in cal.solar_terms_of_year(year)
    ]
    return {"ok": True, "data": {"year": year, "solar_terms": terms}}
