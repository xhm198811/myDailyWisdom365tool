# 晨间问候小程序（Daily Greeting）

每日早晨展示：**天气 · 公历/农历日期与节假日 · 一句敬语问候**。
后端 FastAPI + asyncpg 直连 Supabase Postgres，前端微信小程序。

---

## 一、架构：为什么必须有后端中转层

**微信小程序没有 TCP socket，不能直连 PostgreSQL。**`wx.request` 只支持 HTTPS。
所以连接参数（host/port/user）只能配在服务端，小程序永远不接触数据库凭据。

```
微信小程序 ──HTTPS──> FastAPI 中转层 ──asyncpg(5432)──> Supabase Postgres
   (wx.request)        (聚合 + 缓存 + 降级)                敬语 / 节假日 / 缓存
                            │
                            └──HTTPS──> 和风天气 devapi
```

中转层承担四件事：凭据隔离、多源聚合（一次请求拿齐所有数据）、缓存（避免每次开屏都打第三方 API）、降级（数据库或天气挂了页面照常显示）。

---

## 二、目录结构

```
D:\MywxApp\
├── README.md                      本文件
├── sql/
│   └── 001_init.sql               建表 + 种子语料（在 Supabase SQL Editor 执行）
├── server/                        FastAPI 后端
│   ├── requirements.txt
│   ├── .env.example               → 复制为 .env 后填写
│   ├── app/
│   │   ├── main.py                应用入口、CORS、启动探活
│   │   ├── core/config.py         全部配置（pydantic-settings，无硬编码密钥）
│   │   ├── db/session.py          异步引擎 + 降级开关
│   │   ├── api/v1/
│   │   │   ├── router.py
│   │   │   └── today.py           /today  /greeting/random  /calendar  /health
│   │   └── services/
│   │       ├── calendar_cn.py     农历 · 二十四节气 · 干支生肖 · 传统节日
│   │       ├── weather.py         和风天气 + 三级缓存 + mock 降级
│   │       ├── holiday.py         节假日 / 调休 / 放假倒计时
│   │       └── greeting.py        敬语按场景加权随机
│   └── tests/
│       └── test_calendar.py       历法算法自校验（含权威时刻比对）
├── miniprogram/                   微信小程序
│   ├── config.js                  环境 / API 地址
│   ├── app.js  app.json  app.wxss
│   ├── sitemap.json  project.config.json
│   ├── utils/
│   │   ├── api.js                 wx.request 封装
│   │   └── format.js              天气 emoji 映射、时段问候
│   └── pages/index/               展示页（js / wxml / wxss / json）
└── preview/
    └── index.html                 高保真 Web 预览（连本地后端拉真实数据）
```

---

## 三、数据来源

| 展示项 | 来源 | 说明 |
|---|---|---|
| 公历日期 / 星期 | 后端计算 | 北京时间（UTC+8），不受小程序系统时间影响 |
| 农历年月日、闰月 | `lunardate` 库 | 纯 Python 离线计算，覆盖 1900–2100 |
| 二十四节气 | **自建天文算法** | 计算太阳视黄经后二分求交节时刻，见下 |
| 干支 / 生肖 | 后端计算 | 年干支以农历正月初一为岁首，日干支以 1900-01-01 甲戌日为锚 |
| 农历节日（春节/端午/中秋…） | 后端内置表 | 按农历日期匹配，除夕动态判断腊月最后一天 |
| 公历节日（元旦/教师节/国庆…） | 后端内置表 | 与 `holidays` 表合并去重后展示 |
| 法定节假日、调休补班 | **Supabase `holidays` 表** | 按国务院年度公告维护，每年更新一次 |
| 下一个假期倒计时 | Supabase `holidays` 表 | 查 180 天内最近的 `is_day_off = true` |
| 天气实况 / 预报 / 生活指数 / 空气质量 | 和风天气 devapi | 免费版足够个人使用；未配 Key 自动降级 |
| 敬语问候 | **Supabase `greetings` 表** | 按场景分类、权重随机；DB 挂了用内置语料 |

### 关于节气算法（重点）

没有采用网传的 `sTermInfo` 常数表 + 特殊年份修正表方案 —— 那份表抄错一个数字就会让某个节气差一整天，且无法自测。
改为：**VSOP87 主项截断计算太阳视黄经 → 逐日扫描符号变化 → 二分 60 次求精确时刻 → 转北京时间**，并修正了 ΔT（力学时与世界时之差）。

已用公开发布的 **2024 年二十四节气精确时刻全表**（北京市文物局发布，精确到秒）逐项比对：

- **日期 24/24 全部正确**
- 时刻偏差 -1.5 ~ -8.6 分钟（源于级数截断残留的约 0.01° 黄经误差）

判定节气落在哪一天绰绰有余。校验脚本在 `server/tests/test_calendar.py`，改算法后可直接跑：

```bash
python tests/test_calendar.py
```

若某年需要精确到秒的交节时刻，在 `holidays` 表用 `kind='solar_term'` 覆盖即可，无需改代码。

---

## 四、页面展示逻辑

### 数据聚合（一次请求）

小程序只调 `GET /api/v1/today?city=宁波`，后端返回日期 + 天气 + 敬语三块。

### 1. 日期区

```
9月10日   星期四
2026年 · 农历七月廿九
丙午年【马】 · 日柱 丁亥
[教师节] [工作日]
下一节气   秋分 · 13 天后
假期倒计时 国庆节 · 还有 21 天
```

**作息类型判定按优先级短路：**

| 优先级 | 条件 | 结果 |
|---|---|---|
| 1 | `holidays` 表 `kind = 'makeup_workday'` | 调休补班（周末也算上班） |
| 2 | `holidays` 表 `kind = 'holiday'` 或 `is_day_off = true` | 法定节假日 |
| 3 | 周六 / 周日 | 休息日 |
| 4 | 其余 | 工作日 |

数据库不可用时退化为「仅按周末判断」，页面不会打不开。

### 2. 天气区

城市（点击可切换）+ emoji 图标 + 当前温度 + 天气描述 + 温度区间 + 体感 + 湿度 / 风向风力 / 空气质量 + 生活建议。
`source = 'mock'` 时说明这是示例数据，避免误导。

### 3. 敬语区

**候选链命中即止，逐级回退：**

```
节日 > 节气 > 天气场景(雨/冷/热/晴) > 作息(周末/工作日) > 通用晨间
```

- 天气场景判定：有雨 → `rain`；≤6℃ → `cold`；≥32℃ → `hot`；晴 → `sunny`
- 每条候选先用 SQL `order by (random() * weight) desc limit 1` 从 `greetings` 表加权抽取
- 抽不到才用内置语料，保证任何情况下都有一句

「换一句」调 `/greeting/random`，沿用同一套场景规则。

### 4. 状态与容错

- 首屏先读本地缓存再静默刷新，不白屏
- 请求失败：有缓存展示缓存 + 提示「网络异常，展示上次数据」；无缓存显示错误原因
- 响应里的 `degraded` 字段标出当前降级项（`database` / `weather`），页面底部如实提示

---

## 五、数据库表（Supabase）

| 表 | 用途 | 关键字段 |
|---|---|---|
| `greetings` | 敬语语料 | `category` `trigger_term` `trigger_festival` `weight` `enabled` |
| `holidays` | 节假日与调休 | `day`(唯一) `name` `kind` `is_day_off` |
| `weather_cache` | 天气缓存 | `cache_key`(唯一) `payload`(jsonb) `expire_at` |
| `wx_users` | 小程序用户（二期登录） | `openid`(唯一) |
| `user_settings` | 用户偏好（城市、语气） | `openid` `city_name` `city_id` `tone` |

`holidays.kind` 取值：`holiday` 放假 / `makeup_workday` 调休补班 / `traditional` 农历节日 / `solar_festival` 公历节日。
`is_day_off`：`true` 放假、`false` 补班、`null` 仅展示不影响作息判断。

> ⚠️ 国务院每年 11 月左右发布次年放假安排，调休细则每年都变，
> 需要按官方公告每年 upsert 一次 `holidays` 表。脚本里已写入固定日期的节日作为占位。

---

## 六、实施步骤

### 第 1 步：建库

Supabase Dashboard → SQL Editor → 粘贴 `sql/001_init.sql` → Run。

### 第 2 步：配后端

```bash
cd server
cp .env.example .env
```

填两个值（**你给的连接参数里缺 password，必须补上**）：

```ini
SUPABASE_DB_PASSWORD=<Supabase 数据库密码>
QWEATHER_API_KEY=<和风天气 Key>      # 留空则用 mock 天气，页面照样能跑
```

密码在哪里拿：Supabase → Project Settings → Database → Connection string。

### 第 3 步：起服务

```bash
python -m venv .venv && .venv/Scripts/activate    # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8123
```

打开 <http://127.0.0.1:8123/docs> 看接口文档，或访问：

```
GET /api/v1/today?city=宁波
GET /api/v1/today?city=宁波&d=2026-02-17      # 指定日期，便于验证春节等节日
GET /api/v1/greeting/random
GET /api/v1/calendar?year=2026
GET /api/v1/health
```

响应示例中 `degraded` 为空数组表示数据源全部正常。

### 第 4 步：跑小程序

微信开发者工具 → 导入项目 → 目录选 `miniprogram` → AppID 选「测试号」。

- 开发者工具：详情 → 本地设置 → 勾选**不校验合法域名**（否则 http 请求被拦截）
- 真机调试：把 `config.js` 的 `apiBase` 改成电脑局域网 IP，如 `http://192.168.1.20:8123/api/v1`
- 想先看效果：直接用浏览器打开 `preview/index.html`

### 第 5 步：上线（简版）

1. 后端部署到任意支持 Python 的容器/VPS，配 HTTPS 域名
2. 微信公众平台 → 开发 → 开发管理 → 服务器域名 → 把域名加进 **request 合法域名**
3. `miniprogram/config.js` 切 `ENV = 'prod'` 并填线上地址
4. 开发者工具上传代码 → 提交审核

---

## 七、接口响应示例

`GET /api/v1/today?city=宁波`

```json
{
  "ok": true,
  "data": {
    "date": {
      "date": "2026-09-10",
      "weekday": "星期四",
      "day_type": "workday",
      "day_type_label": "工作日",
      "festivals": ["教师节"],
      "solar_term": null,
      "is_day_off": false,
      "next_holiday": null,
      "lunar": { "month_cn": "七月", "day_cn": "廿九", "year_cn": "丙午年", "zodiac": "马" },
      "ganzhi_day": "丁亥",
      "next_solar_term": { "name": "秋分", "date": "2026-09-23", "days": 13 }
    },
    "weather": {
      "city": "宁波", "text": "中雨", "icon": "306", "temp": 19,
      "feels_like": 20, "temp_min": 18, "temp_max": 22,
      "humidity": 76, "wind_dir": "东南风", "wind_scale": "3级",
      "aqi": 60, "aqi_category": "优",
      "tips": "雨势明显，路面湿滑，注意安全。",
      "source": "mock", "cached": false
    },
    "greeting": { "content": "今日教师节。愿你平安喜乐，诸事顺遂。", "category": "festival" }
  },
  "degraded": ["database", "weather"],
  "generated_at": "2026-09-10T14:55:04+08:00"
}
```

---

## 八、已知限制

- 敬语语料库里 `festival` 分类目前只覆盖了春节/元宵/端午/中秋/重阳，其余节日会回退到下一级场景
- `holidays` 表只写入了固定日期的节日占位，**调休补班需按国务院公告手工补充**
- 节气时刻精度 ±9 分钟（见第三节）
- 尚未接入 `wx.login`，`wx_users` / `user_settings` 表已建好但未使用（二期）
- 后端用裸 SQL（`text()`）而非 ORM，因为查询都很简单；如需 ORM 可后续加
