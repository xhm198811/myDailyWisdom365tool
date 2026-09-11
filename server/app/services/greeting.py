"""敬语问候：按场景优先级从 Supabase 加权随机抽取。

选取优先级（命中即止，逐级回退）：
  节日 > 节气 > 天气场景（雨/冷/热/晴） > 作息（周末/工作日） > 通用晨间

数据库不可用时用内置语料兜底，保证页面永远有一句问候。
"""
from __future__ import annotations

import random

from sqlalchemy import text

from app.db.session import db_available, session_scope

# 内置兜底语料（数据库不可用时使用）
FALLBACK: dict[str, list[str]] = {
    "morning": [
        "晨安。愿你今日心无挂碍，步履从容。",
        "早安。新的一天，愿所遇皆温柔，所行皆坦途。",
        "清晨吉祥。愿你今日诸事顺遂，喜乐安康。",
        "早安。愿你今日心境明朗，如这清晨的光。",
    ],
    "weekend": [
        "周末愉快。愿你慢下来，好好陪陪自己和家人。",
        "早安。难得的休息日，愿你睡到自然醒，心满意足。",
    ],
    "workday": [
        "早安，愿你今日元气满满，稳稳向前。",
        "晨安。工作日也要好好照顾自己，记得吃早餐。",
    ],
    "rain": ["今日有雨，路滑慢行。愿你带伞出门，也带好心情。",
             "雨天早安。愿你心晴，便不惧天阴。"],
    "sunny": ["天朗气清，惠风和畅。愿你不负这好天气。",
              "阳光正好，早安。愿你今日也闪闪发光。"],
    "cold": ["降温了，早安。记得添衣保暖，别让自己受凉。",
             "天气转凉，愿你有衣暖身，有人暖心。"],
    "hot": ["今日炎热，早安。愿你心静自然凉，多喝水。",
            "酷暑难当，愿你寻得一处清凉，安放身心。"],
    "solar_term": ["今日{solar_term}。愿你顺时而动，安顿身心。"],
    "festival": ["今日{festival}。愿你平安喜乐，诸事顺遂。"],
}


async def _pick_from_db(category: str, term: str | None, festival: str | None) -> str | None:
    if not db_available():
        return None
    try:
        async with session_scope() as s:
            if s is None:
                return None
            row = (
                await s.execute(
                    text(
                        "select content from public.greetings "
                        "where enabled = true and category = :cat "
                        "  and coalesce(trigger_term, '') = coalesce(:term, '') "
                        "  and coalesce(trigger_festival, '') = coalesce(:fest, '') "
                        "order by (random() * weight) desc limit 1"
                    ),
                    {"cat": category, "term": term, "fest": festival},
                )
            ).first()
            return row[0] if row else None
    except Exception:
        return None


def _pick_fallback(category: str, term: str | None, festival: str | None) -> str:
    pool = FALLBACK.get(category)
    if not pool:
        pool = FALLBACK["morning"]
    content = random.choice(pool)
    return content.format(solar_term=term or "", festival=festival or "")


def _weather_category(weather: dict | None) -> str | None:
    if not weather:
        return None
    if weather.get("source") == "mock" and not weather.get("text"):
        return None
    if weather.get("is_rainy") or "雨" in (weather.get("text") or ""):
        return "rain"
    temp = weather.get("temp")
    try:
        temp_f = float(temp)
    except (TypeError, ValueError):
        temp_f = None
    if temp_f is not None:
        if temp_f <= 6:
            return "cold"
        if temp_f >= 32:
            return "hot"
    if "晴" in (weather.get("text") or ""):
        return "sunny"
    return None


def build_chain(day_info: dict, weather: dict | None) -> list[tuple[str, str | None, str | None]]:
    """返回 (category, term, festival) 的候选链，按顺序尝试。"""
    chain: list[tuple[str, str | None, str | None]] = []

    for fest in day_info.get("festivals") or []:
        chain.append(("festival", None, fest))

    term = day_info.get("solar_term")
    if term:
        chain.append(("solar_term", term, None))

    wc = _weather_category(weather)
    if wc:
        chain.append((wc, None, None))

    day_type = day_info.get("day_type")
    if day_type in ("weekend", "holiday"):
        chain.append(("weekend", None, None))
    elif day_type in ("workday", "makeup_workday"):
        # 调休补班日虽然可能是周六周日，本质上还是要上班，走工作日语料
        chain.append(("workday", None, None))

    chain.append(("morning", None, None))
    return chain


async def pick_greeting(day_info: dict, weather: dict | None) -> dict:
    for category, term, festival in build_chain(day_info, weather):
        content = await _pick_from_db(category, term, festival)
        if content:
            return {"content": content, "category": category, "source": "database"}
        # 兜底：仅当该分类有内置语料时才用，否则继续尝试下一级
        if category in FALLBACK:
            return {
                "content": _pick_fallback(category, term, festival),
                "category": category,
                "source": "builtin",
            }
    return {
        "content": _pick_fallback("morning", None, None),
        "category": "morning",
        "source": "builtin",
    }
