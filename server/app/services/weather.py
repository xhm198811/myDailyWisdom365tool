"""天气服务：和风天气 devapi 为主，无 key 时自动降级 mock。

缓存策略（三级，逐级回退）：
  1. 进程内存（秒级，零成本）
  2. Supabase weather_cache 表（跨进程 / 多实例共享，TTL 默认 600 秒）
  3. 直连和风 API
  4. 内置 mock（保证任何情况下页面都有内容可展示）
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.db.session import db_available, session_scope

CST = timezone(timedelta(hours=8))

_memory: dict[str, tuple[float, dict]] = {}
TIMEOUT = 6.0

# 和风天气图标码 -> 展示文案需要的分类，用于挑选敬语场景
_RAIN_CODES = set(range(300, 400)) | set(range(400, 410)) | {104, 154, 305, 306, 307, 308, 309, 314, 315, 316, 317, 318, 350, 351, 399}


# ---------------------------------------------------------------------------
# 缓存
# ---------------------------------------------------------------------------
async def _cache_get(key: str) -> dict | None:
    hit = _memory.get(key)
    if hit and hit[0] > time.time():
        return hit[1]

    if db_available():
        try:
            async with session_scope() as s:
                if s is not None:
                    row = (
                        await s.execute(
                            text(
                                "select payload from public.weather_cache "
                                "where cache_key = :k and expire_at > now()"
                            ),
                            {"k": key},
                        )
                    ).first()
                    if row:
                        payload = row[0]
                        _memory[key] = (time.time() + settings.WEATHER_CACHE_TTL, payload)
                        return payload
        except Exception:
            pass
    return None


async def _cache_set(key: str, payload: dict) -> None:
    _memory[key] = (time.time() + settings.WEATHER_CACHE_TTL, payload)
    if not db_available():
        return
    try:
        async with session_scope() as s:
            if s is None:
                return
            await s.execute(
                text(
                    "insert into public.weather_cache (cache_key, payload, expire_at) "
                    "values (:k, cast(:p as jsonb), now() + make_interval(secs => :ttl)) "
                    "on conflict (cache_key) do update set "
                    "payload = excluded.payload, fetched_at = now(), expire_at = excluded.expire_at"
                ),
                {
                    "k": key,
                    "p": json.dumps(payload, ensure_ascii=False),
                    "ttl": float(settings.WEATHER_CACHE_TTL),
                },
            )
            await s.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 和风天气
# ---------------------------------------------------------------------------
async def _geo_location(city: str) -> str | None:
    """城市名 -> 和风 location id。经纬度精确，城市名可能有歧义。"""
    if not settings.QWEATHER_API_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(
                f"https://{settings.QWEATHER_GEO_HOST}/v2/city/lookup",
                params={"location": city, "range": "cn", "number": 1,
                        "key": settings.QWEATHER_API_KEY},
            )
        data = r.json()
        if data.get("code") == "200" and data.get("location"):
            return data["location"][0]["id"]
    except Exception:
        pass
    return None


async def _qweather(path: str, params: dict) -> dict | None:
    if not settings.QWEATHER_API_KEY:
        return None
    params = {**params, "key": settings.QWEATHER_API_KEY}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get(f"https://{settings.QWEATHER_API_HOST}{path}", params=params)
        data = r.json()
        return data if data.get("code") == "200" else None
    except Exception:
        return None


def _is_rainy(icon: str) -> bool:
    try:
        return int(icon) in _RAIN_CODES
    except (TypeError, ValueError):
        return "雨" in str(icon)


async def _from_qweather(city: str, lat: float | None, lon: float | None) -> dict | None:
    if lat is not None and lon is not None:
        loc = f"{lon:.2f},{lat:.2f}"
    else:
        loc = await _geo_location(city)
    if not loc:
        return None

    now = await _qweather("/v7/weather/now", {"location": loc})
    if not now or not now.get("now"):
        return None

    n = now["now"]
    daily = await _qweather("/v7/weather/3d", {"location": loc}) or {}
    d0 = (daily.get("daily") or [{}])[0]

    air = await _qweather("/v7/air/now", {"location": loc}) or {}
    air_now = air.get("now") or {}

    indices = await _qweather("/v7/indices/1d", {"location": loc, "type": "0"}) or {}
    tips = ""
    idx_list = indices.get("daily") or []
    for item in idx_list:
        if item.get("type") in ("1", "2", "3"):  # 运动 / 洗车 / 穿衣
            tips = item.get("text") or ""
            if tips:
                break
    if not tips and idx_list:
        tips = idx_list[0].get("text") or ""

    try:
        icon = n.get("icon") or ""
        payload = {
            "city": city,
            "text": n.get("text", ""),
            "icon": icon,
            "temp": int(n.get("temp", 0)),
            "feels_like": int(n.get("feelsLike", n.get("temp", 0))),
            "temp_min": int(d0.get("tempMin", n.get("tempMin", 0))),
            "temp_max": int(d0.get("tempMax", n.get("tempMax", 0))),
            "humidity": int(n.get("humidity") or 0),
            "wind_dir": n.get("windDir", ""),
            "wind_scale": n.get("windScale", ""),
            "precip": float(n.get("precip") or 0),
            "aqi": air_now.get("aqi"),
            "aqi_category": air_now.get("category"),
            "tips": tips,
            "sunrise": d0.get("sunrise", ""),
            "sunset": d0.get("sunset", ""),
            "uv_index": d0.get("uvIndex", ""),
            "is_rainy": _is_rainy(icon),
            "source": "qweather",
            "obs_time": n.get("obsTime", ""),
        }
    except (TypeError, ValueError):
        return None
    return payload


# ---------------------------------------------------------------------------
# mock 兜底
# ---------------------------------------------------------------------------
def _mock(city: str, today: date) -> dict:
    # 用日期做种子，保证同一天多次请求结果稳定，不会每次刷新都变
    seed = today.toordinal() % 7
    table = [
        ("晴", "100", 26, 22, 31, "天气晴好，宜出门走走。"),
        ("多云", "101", 25, 21, 29, "云层较厚，体感舒适。"),
        ("阴", "104", 23, 20, 27, "天色阴沉，记得带件外套。"),
        ("小雨", "305", 21, 19, 24, "有雨，出门请带伞。"),
        ("中雨", "306", 19, 18, 22, "雨势明显，路面湿滑，注意安全。"),
        ("雷阵雨", "302", 27, 23, 32, "午后可能有雷雨，留意天气变化。"),
        ("晴", "100", 30, 25, 34, "天气炎热，注意补水防晒。"),
    ]
    text, icon, temp, tmin, tmax, tips = table[seed]
    return {
        "city": city,
        "text": text,
        "icon": icon,
        "temp": temp,
        "feels_like": temp + 1,
        "temp_min": tmin,
        "temp_max": tmax,
        "humidity": 60 + seed * 4,
        "wind_dir": "东南风",
        "wind_scale": "3级",
        "precip": 0.0,
        "aqi": 40 + seed * 5,
        "aqi_category": "优",
        "tips": tips,
        "sunrise": "05:32",
        "sunset": "18:20",
        "uv_index": "5",
        "is_rainy": icon.startswith("3"),
        "source": "mock",
        "obs_time": datetime.now(CST).strftime("%Y-%m-%dT%H:%M+08:00"),
    }


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
async def get_weather(
    city: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    today: date | None = None,
) -> dict:
    city = city or settings.DEFAULT_CITY
    today = today or datetime.now(CST).date()
    key = f"now:{city}:{lat or ''},{lon or ''}:{today.isoformat()}"

    cached = await _cache_get(key)
    if cached:
        return {**cached, "cached": True}

    payload = None
    if settings.QWEATHER_API_KEY:
        payload = await _from_qweather(city, lat, lon)
    if payload is None:
        payload = _mock(city, today)

    await _cache_set(key, payload)
    return {**payload, "cached": False}
