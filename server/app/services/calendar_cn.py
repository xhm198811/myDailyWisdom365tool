"""中国传统历法计算：农历、二十四节气、干支生肖、传统节日。

设计取舍：
- 农历    -> 用 lunardate 库（纯 Python，覆盖 1900-2100，久经验证）
- 二十四节气 -> 自己算太阳视黄经（VSOP87 截断级数），二分求时刻。
             不采用网传的 sTermInfo 常数表 + 特殊年份修正表方案：那份表一旦抄错
             一个数字就会让某个节气差一天，且难以自测。天文算法只依赖标准公式，
             精度约 ±1 分钟，确定节气所在日期足够可靠，且可离线自校验。
- 干支    -> 以农历正月初一为岁首（民俗惯例；命理派以立春为岁首，代码里已注明切换点）
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from lunardate import LunarDate

CST = timezone(timedelta(hours=8))

TIAN_GAN = "甲乙丙丁戊己庚辛壬癸"
DI_ZHI = "子丑寅卯辰巳午未申酉戌亥"
ZODIACS = "鼠牛虎兔龙蛇马羊猴鸡狗猪"

# 二十四节气：按黄经排列（小寒 285° 起），索引 0 = 小寒
SOLAR_TERMS: list[tuple[str, int]] = [
    ("小寒", 285), ("大寒", 300), ("立春", 315), ("雨水", 330),
    ("惊蛰", 345), ("春分", 0),   ("清明", 15),  ("谷雨", 30),
    ("立夏", 45),  ("小满", 60),  ("芒种", 75),  ("夏至", 90),
    ("小暑", 105), ("大暑", 120), ("立秋", 135), ("处暑", 150),
    ("白露", 165), ("秋分", 180), ("寒露", 195), ("霜降", 210),
    ("立冬", 225), ("小雪", 240), ("大雪", 255), ("冬至", 270),
]

LUNAR_MONTH_CN = ["正", "二", "三", "四", "五", "六",
                  "七", "八", "九", "十", "冬", "腊"]

# 农历传统节日（月, 日）-> 名称
LUNAR_FESTIVALS = {
    (1, 1): "春节",
    (1, 15): "元宵节",
    (2, 2): "龙抬头",
    (5, 5): "端午节",
    (7, 7): "七夕",
    (7, 15): "中元节",
    (8, 15): "中秋节",
    (9, 9): "重阳节",
    (12, 8): "腊八节",
}

# 公历节日（月, 日）-> 名称。法定放假与否由 holidays 表决定，这里只负责展示。
SOLAR_FESTIVALS = {
    (1, 1): "元旦",
    (3, 8): "妇女节",
    (3, 12): "植树节",
    (4, 1): "愚人节",
    (5, 1): "劳动节",
    (5, 4): "青年节",
    (6, 1): "儿童节",
    (7, 1): "建党节",
    (8, 1): "建军节",
    (9, 10): "教师节",
    (10, 1): "国庆节",
    (11, 11): "光棍节",
    (12, 25): "圣诞节",
}


# ---------------------------------------------------------------------------
# 儒略日与太阳视黄经
# ---------------------------------------------------------------------------
def _jd_from_utc(dt: datetime) -> float:
    """公历（naive UTC datetime）-> 儒略日。Meeus 公式。"""
    y, m = dt.year, dt.month
    d = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def _utc_from_jd(jd: float) -> datetime:
    """儒略日 -> 公历（naive UTC datetime）。Meeus 公式。"""
    jd += 0.5
    f, z = math.modf(jd)
    z = int(z)
    a = z
    if z >= 2299161:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day_frac = b - d - int(30.6001 * e) + f
    day = int(day_frac)
    frac = day_frac - day
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    return (
        datetime(year, month, day, tzinfo=timezone.utc)
        + timedelta(days=frac)
    ).replace(tzinfo=None)


def _delta_t(year: float) -> float:
    """ΔT = 力学时 - 世界时（秒）。太阳位置要用力学时，漏掉会系统性偏早约 70 秒。
    取自 Espenak & Meeus 的 2005-2050 拟合式，范围外给常数兜底。"""
    if 2005.0 <= year <= 2050.0:
        t = year - 2000.0
        return 62.92 + 0.32217 * t + 0.005589 * t * t
    return 70.0


def solar_longitude(jd_ut: float) -> float:
    """太阳视黄经（度），VSOP87 主项截断。

    精度说明（已实测校准，见 tests/test_calendar.py）：与公开发布的 2024 年
    二十四节气精确时刻逐项比对，日期 24/24 全部正确，时刻偏差 -1.5 ~ -8.6 分钟。
    偏差来自中心差级数截断残留的约 0.01 度黄经误差（≈14 分钟窗口），
    判定节气落在哪一天绰绰有余；若某年需要精确到秒的交节时刻，
    可在 holidays 表用 kind='solar_term' 覆盖，或在 SQL 里 upsert 指定日期。
    """
    year = 2000.0 + (jd_ut - 2451545.0) / 365.25
    jd = jd_ut + _delta_t(year) / 86400.0  # UT -> TT
    t = (jd - 2451545.0) / 36525.0
    # 平黄经
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t * t
    # 平近点角
    m = math.radians(357.52911 + 35999.05029 * t - 0.0001537 * t * t)
    # 中心差
    c = (
        (1.914602 - 0.004817 * t) * math.sin(m)
        + (0.019993 - 0.000101 * t) * math.sin(2 * m)
        + 0.000289 * math.sin(3 * m)
    )
    lon = l0 + c
    # 光行差 + 章动修正
    omega = math.radians(125.04 - 1934.136 * t)
    lon = lon - 0.00569 - 0.00478 * math.sin(omega)
    return lon % 360.0


def _solve_term(year: int, target_deg: float) -> datetime | None:
    """二分求某年太阳黄经首次达到 target_deg 的时刻（返回北京时间）。"""
    def delta(jd: float) -> float:
        """lon 与 target 的最小夹角，符号从负穿到正即为节气时刻。"""
        return ((solar_longitude(jd) - target_deg + 180.0) % 360.0) - 180.0

    jd = _jd_from_utc(datetime(year, 1, 1))
    end = _jd_from_utc(datetime(year + 1, 1, 2))
    prev = delta(jd)
    step = 1.0
    while jd < end:
        nxt = jd + step
        cur = delta(nxt)
        if prev < 0.0 <= cur:
            lo, hi = jd, nxt
            for _ in range(60):
                mid = (lo + hi) / 2.0
                if delta(mid) < 0.0:
                    lo = mid
                else:
                    hi = mid
            utc_dt = _utc_from_jd((lo + hi) / 2.0)
            return (utc_dt.replace(tzinfo=timezone.utc)).astimezone(CST)
        prev, jd = cur, nxt
    return None


@lru_cache(maxsize=8)
def solar_terms_of_year(year: int) -> tuple[tuple[str, datetime], ...]:
    """某年全部 24 个节气的北京时间时刻，按时间排序。"""
    items: list[tuple[str, datetime]] = []
    for name, deg in SOLAR_TERMS:
        dt = _solve_term(year, deg)
        if dt is not None:
            items.append((name, dt))
    items.sort(key=lambda x: x[1])
    return tuple(items)


def solar_term_on(date) -> str | None:
    """返回 date 当天的节气名（按北京时间判定），没有则 None。"""
    terms = solar_terms_of_year(date.year)
    for name, dt in terms:
        if dt.date() == date:
            return name
    return None


def next_solar_term(date) -> dict | None:
    """下一个节气及其距今天数。"""
    for year in (date.year, date.year + 1):
        for name, dt in solar_terms_of_year(year):
            if dt.date() > date:
                return {"name": name, "date": dt.date().isoformat(),
                        "days": (dt.date() - date).days}
    return None


# ---------------------------------------------------------------------------
# 农历
# ---------------------------------------------------------------------------
def solar_to_lunar(date) -> dict:
    ld = LunarDate.fromSolarDate(date.year, date.month, date.day)
    return {
        "year": ld.year,
        "month": ld.month,
        "day": ld.day,
        "is_leap_month": bool(ld.isLeapMonth),
        "month_cn": ("闰" if ld.isLeapMonth else "") + LUNAR_MONTH_CN[ld.month - 1] + "月",
        "day_cn": lunar_day_cn(ld.day),
        "year_cn": f"{ganzhi_of_lunar_year(ld.year)}年",
        "zodiac": ZODIACS[(ld.year - 4) % 12],
    }


_CN_NUM = "一二三四五六七八九"


def lunar_day_cn(day: int) -> str:
    """农历日 -> 中文，如 1->初一 15->十五 21->廿一 30->三十。"""
    if day == 10:
        return "初十"
    if day == 20:
        return "二十"
    if day == 30:
        return "三十"
    if day < 10:
        return "初" + _CN_NUM[day - 1]
    if day < 20:
        return "十" + _CN_NUM[day - 11]
    if day < 30:
        return "廿" + _CN_NUM[day - 21]
    return "三十"


def ganzhi_of_lunar_year(lunar_year: int) -> str:
    """农历年干支。以正月初一为岁首（命理派以立春为岁首，改这里即可）。"""
    i = (lunar_year - 4) % 10
    j = (lunar_year - 4) % 12
    return TIAN_GAN[i] + DI_ZHI[j]


def ganzhi_of_day(date) -> str:
    """日干支。锚点：1900-01-01 为甲戌日（60 甲子序号 10）。"""
    base = datetime(1900, 1, 1).date()
    offset = (date - base).days
    idx = (10 + offset) % 60
    return TIAN_GAN[idx % 10] + DI_ZHI[idx % 12]


def lunar_festival_on(date) -> str | None:
    """农历传统节日。除夕按当年腊月最后一天动态判断。"""
    ld = LunarDate.fromSolarDate(date.year, date.month, date.day)
    name = LUNAR_FESTIVALS.get((ld.month, ld.day))
    if name:
        return name
    # 除夕 = 腊月最后一天（可能是廿九）
    if ld.month == 12 and ld.day == _lunar_month_last_day(ld.year, 12):
        return "除夕"
    # 小年：北方廿三（南方廿四，此处取通行的廿三）
    if ld.month == 12 and ld.day == 23:
        return "小年"
    return None


def _lunar_month_last_day(lunar_year: int, month: int) -> int:
    """该农历月最后一天是 29 还是 30。用次月初一减一天反推。"""
    try:
        if month == 12:
            nxt_solar = LunarDate(lunar_year + 1, 1, 1).toSolarDate()
        else:
            nxt_solar = LunarDate(lunar_year, month + 1, 1).toSolarDate()
        last = nxt_solar - timedelta(days=1)
        return LunarDate.fromSolarDate(last.year, last.month, last.day).day
    except Exception:
        return 29


def solar_festival_on(date) -> str | None:
    return SOLAR_FESTIVALS.get((date.month, date.day))
