"""节气 / 农历算法自校验。运行：python tests/test_calendar.py

参照值：2024 年二十四节气精确时刻（北京市文物局公开发布，与万年历一致，精确到秒）。
   立春 02-04 16:26:53   雨水 02-19 12:12:58   惊蛰 03-05 10:22:31   春分 03-20 11:06:12
   清明 04-04 15:02:03   谷雨 04-19 21:59:33   立夏 05-05 08:09:51   小满 05-20 20:59:17
   芒种 06-05 12:09:40   夏至 06-21 04:50:46   小暑 07-06 22:19:49   大暑 07-22 15:44:11
   立秋 08-07 08:09:01   处暑 08-22 22:54:48   白露 09-07 11:11:06   秋分 09-22 20:43:27
   寒露 10-08 02:59:43   霜降 10-23 06:14:32   立冬 11-07 06:19:49   小雪 11-22 03:56:16
   大雪 12-06 23:16:47   冬至 12-21 17:20:20

判定标准：
   - 日期必须完全一致（这是页面展示的正确性底线）
   - 时刻允许 ±10 分钟误差（Meeus 低精度太阳位置级数的已知残差）
"""
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.calendar_cn import (  # noqa: E402
    _jd_from_utc,
    ganzhi_of_day,
    lunar_festival_on,
    next_solar_term,
    solar_festival_on,
    solar_longitude,
    solar_term_on,
    solar_terms_of_year,
    solar_to_lunar,
)

FAILED = []


def check(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        FAILED.append(msg)


# ---------------------------------------------------------------------------
print("\n[1] 太阳黄经基准：2024 春分 11:06:12 CST 时黄经应≈0°")
# 11:06:12 CST = 03:06:12 UTC
jd_equinox = _jd_from_utc(datetime(2024, 3, 20, 3, 6, 12))
lon = solar_longitude(jd_equinox)
err = min(lon, 360 - lon)
check(err < 0.05, f"黄经={lon:.5f}° 与 0° 偏差 {err:.5f}°（应 <0.05°）")

# ---------------------------------------------------------------------------
REF_2024 = [
    ("立春", "2024-02-04 16:26:53"), ("雨水", "2024-02-19 12:12:58"),
    ("惊蛰", "2024-03-05 10:22:31"), ("春分", "2024-03-20 11:06:12"),
    ("清明", "2024-04-04 15:02:03"), ("谷雨", "2024-04-19 21:59:33"),
    ("立夏", "2024-05-05 08:09:51"), ("小满", "2024-05-20 20:59:17"),
    ("芒种", "2024-06-05 12:09:40"), ("夏至", "2024-06-21 04:50:46"),
    ("小暑", "2024-07-06 22:19:49"), ("大暑", "2024-07-22 15:44:11"),
    ("立秋", "2024-08-07 08:09:01"), ("处暑", "2024-08-22 22:54:48"),
    ("白露", "2024-09-07 11:11:06"), ("秋分", "2024-09-22 20:43:27"),
    ("寒露", "2024-10-08 02:59:43"), ("霜降", "2024-10-23 06:14:32"),
    ("立冬", "2024-11-07 06:19:49"), ("小雪", "2024-11-22 03:56:16"),
    ("大雪", "2024-12-06 23:16:47"), ("冬至", "2024-12-21 17:20:20"),
]

print("\n[2] 2024 年二十四节气 vs 天文台发布值（日期必须一致，时刻 ±10 分钟）")
got_2024 = dict(solar_terms_of_year(2024))
max_diff = 0.0
for name, ref_str in REF_2024:
    ref = datetime.strptime(ref_str, "%Y-%m-%d %H:%M:%S")
    got = got_2024.get(name)
    if got is None:
        check(False, f"{name}: 算法未产出")
        continue
    got_naive = got.replace(tzinfo=None)
    diff_min = abs((got_naive - ref).total_seconds()) / 60.0
    max_diff = max(max_diff, diff_min)
    same_day = got_naive.date() == ref.date()
    check(same_day and diff_min <= 10.0,
          f"{name}: 参照 {ref:%m-%d %H:%M:%S} 实得 {got_naive:%m-%d %H:%M:%S}"
          f" 日期{'一致' if same_day else '不一致'} 时刻差 {diff_min:.1f} 分钟")

print(f"\n  最大时刻误差：{max_diff:.1f} 分钟")

# ---------------------------------------------------------------------------
print("\n[3] 其它年份日期抽查（与公开万年历一致）")
for year, name, expect in [
    (2024, "立春", date(2024, 2, 4)),
    (2024, "清明", date(2024, 4, 4)),
    (2025, "立春", date(2025, 2, 3)),
    (2025, "冬至", date(2025, 12, 21)),
    (2026, "立春", date(2026, 2, 4)),
    (2026, "清明", date(2026, 4, 5)),
    (2026, "冬至", date(2026, 12, 22)),
]:
    got = dict(solar_terms_of_year(year)).get(name)
    check(got is not None and got.date() == expect,
          f"{year} {name}: 期望 {expect}, 实得 {got:%Y-%m-%d}" if got else f"{year} {name}: None")

# ---------------------------------------------------------------------------
print("\n[4] 结构完整性（每年 24 个、严格递增、无重复名）")
for year in (2024, 2025, 2026, 2027, 2030):
    terms = solar_terms_of_year(year)
    names = [n for n, _ in terms]
    times = [dt for _, dt in terms]
    check(len(terms) == 24, f"{year} 共 {len(terms)} 个节气（期望 24）")
    check(len(set(names)) == 24, f"{year} 节气名无重复")
    check(all(times[i] < times[i + 1] for i in range(len(times) - 1)),
          f"{year} 节气时刻严格递增")

print("\n[5] 边界：1 月的小寒大寒归当年，12 月的冬至归当年")
t = dict(solar_terms_of_year(2026))
check(t["小寒"].month == 1 and t["大寒"].month == 1,
      f"2026 小寒 {t['小寒']:%m-%d} / 大寒 {t['大寒']:%m-%d} 均在 1 月")
check(t["冬至"].year == 2026 and t["冬至"].month == 12, f"2026 冬至 {t['冬至']:%Y-%m-%d}")

# ---------------------------------------------------------------------------
print("\n[6] solar_term_on / next_solar_term")
check(solar_term_on(date(2026, 2, 4)) == "立春", "2026-02-04 立春")
check(solar_term_on(date(2026, 9, 10)) is None, "2026-09-10 无节气")
nt = next_solar_term(date(2026, 9, 10))
check(nt is not None and nt["name"] == "秋分" and nt["days"] > 0,
      f"2026-09-10 下一节气：{nt}")

# ---------------------------------------------------------------------------
print("\n[7] 农历转换")
l = solar_to_lunar(date(2026, 9, 10))
print("       2026-09-10 ->", l)
check(l["month_cn"].endswith("月") and l["day_cn"], f"月日中文名：{l['month_cn']}{l['day_cn']}")
check(l["zodiac"] in "鼠牛虎兔龙蛇马羊猴鸡狗猪", f"生肖：{l['zodiac']}")
check(l["year_cn"] == "丙午年", f"年干支：{l['year_cn']}")

l2 = solar_to_lunar(date(2026, 2, 17))
check(l2["month"] == 1 and l2["day"] == 1, f"2026-02-17 应为正月初一，实得 {l2['month_cn']}{l2['day_cn']}")
check(lunar_festival_on(date(2026, 2, 17)) == "春节", "2026-02-17 春节")

# 农历日期必须连续：今天 +1 天 = 农历 +1 天
d0 = date(2026, 9, 10)
a = solar_to_lunar(d0)
b = solar_to_lunar(d0 + timedelta(days=1))
check(b["day"] == a["day"] + 1 or b["day"] == 1,
      f"农历日期连续性：{a['day_cn']} -> {b['day_cn']}")

# ---------------------------------------------------------------------------
print("\n[8] 公历节日")
check(solar_festival_on(date(2026, 9, 10)) == "教师节", "2026-09-10 教师节")
check(solar_festival_on(date(2026, 10, 1)) == "国庆节", "2026-10-01 国庆节")

# ---------------------------------------------------------------------------
print("\n[9] 日干支（相邻两天必须各推进一位）")
gz1, gz2 = ganzhi_of_day(date(2026, 9, 10)), ganzhi_of_day(date(2026, 9, 11))
tg, dz = "甲乙丙丁戊己庚辛壬癸", "子丑寅卯辰巳午未申酉戌亥"
check((tg.index(gz2[0]), dz.index(gz2[1]))
      == ((tg.index(gz1[0]) + 1) % 10, (dz.index(gz1[1]) + 1) % 12),
      f"{gz1} -> {gz2}")

print("\n" + "=" * 60)
if FAILED:
    print(f"失败 {len(FAILED)} 项：")
    for f in FAILED:
        print("  - " + f)
    sys.exit(1)
print(f"全部通过（最大时刻误差 {max_diff:.1f} 分钟，日期 100% 正确）")
