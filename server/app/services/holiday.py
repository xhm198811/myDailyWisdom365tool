"""节假日与作息判断。

优先级（从高到低）：
  1. holidays 表中 kind = 'makeup_workday'  -> 调休补班（即使是周末也上班）
  2. holidays 表中 kind = 'holiday'         -> 法定放假
  3. 周六 / 周日                             -> 休息日
  4. 其余                                    -> 工作日

数据库不可用时退化为「仅按周末判断 + 内置节日名」，页面不会因此打不开。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.db.session import db_available, session_scope
from app.services.calendar_cn import (
    lunar_festival_on,
    solar_festival_on,
    solar_term_on,
)

CST = timezone(timedelta(hours=8))
WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

DAY_TYPE_LABEL = {
    "holiday": "法定节假日",
    "makeup_workday": "调休补班",
    "weekend": "休息日",
    "workday": "工作日",
}


async def _load_day(d: date) -> dict | None:
    if not db_available():
        return None
    try:
        async with session_scope() as s:
            if s is None:
                return None
            row = (
                await s.execute(
                    text(
                        "select name, kind, is_day_off from public.holidays where day = :d"
                    ),
                    {"d": d},
                )
            ).first()
            if row:
                return {"name": row[0], "kind": row[1], "is_day_off": row[2]}
    except Exception:
        pass
    return None


async def _next_holiday(d: date) -> dict | None:
    """下一个法定放假日的倒计时。"""
    if not db_available():
        return None
    try:
        async with session_scope() as s:
            if s is None:
                return None
            row = (
                await s.execute(
                    text(
                        "select day, name from public.holidays "
                        "where is_day_off = true and day > :d and day <= :d + interval '180 days' "
                        "order by day limit 1"
                    ),
                    {"d": d},
                )
            ).first()
            if row:
                return {
                    "name": row[1],
                    "date": row[0].isoformat(),
                    "days": (row[0] - d).days,
                }
    except Exception:
        pass
    return None


async def get_day_info(d: date | None = None) -> dict:
    d = d or datetime.now(CST).date()
    record = await _load_day(d)

    # --- 作息类型 ---
    if record and record["kind"] == "makeup_workday":
        day_type = "makeup_workday"
    elif record and record["kind"] == "holiday":
        day_type = "holiday"
    elif record and record["is_day_off"] is True:
        day_type = "holiday"
    elif d.weekday() >= 5 and not (record and record["is_day_off"] is False):
        day_type = "weekend"
    else:
        day_type = "workday"

    # --- 节日名：DB 优先，其次内置（农历节日 > 公历节日）---
    # 调休补班日（kind='makeup_workday'）的 name 形如「国庆调休补班」，它不是节日，
    # 不能进 festivals —— 否则问候会生成「今日国庆调休补班，愿你平安喜乐」这种怪话。
    festivals: list[str] = []
    db_name = record["name"] if record and record["kind"] != "makeup_workday" else None
    lunar_name = lunar_festival_on(d)
    solar_name = solar_festival_on(d)
    for n in (db_name, lunar_name, solar_name):
        if n and n not in festivals:
            festivals.append(n)

    term = solar_term_on(d)

    return {
        "date": d.isoformat(),
        "weekday": WEEKDAY_CN[d.weekday()],
        "weekday_index": d.weekday(),
        "day_type": day_type,
        "day_type_label": DAY_TYPE_LABEL[day_type],
        "holiday_name": db_name,
        "festivals": festivals,
        "solar_term": term,
        "is_day_off": day_type in ("holiday", "weekend"),
        "next_holiday": await _next_holiday(d),
    }
