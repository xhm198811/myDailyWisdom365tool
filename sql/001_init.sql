-- =============================================================================
-- 001_init.sql  每日问候小程序 · Supabase (PostgreSQL) 初始化脚本
-- 执行方式：Supabase Dashboard -> SQL Editor 全量粘贴执行；或 psql -f 001_init.sql
-- 幂等：全部使用 create table if not exists / on conflict do nothing，可重复执行
--
-- 注意：本脚本默认你用 postgres 直连账号操作（Supabase 的 postgres 角色带
-- BYPASSRLS，不受 RLS 影响）。如果后续改用 anon/service key 走 PostgREST，
-- 需要为每张表单独补 RLS 策略。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. 敬语语料库
-- -----------------------------------------------------------------------------
create table if not exists public.greetings (
    id          bigserial primary key,
    content     text        not null,
    category    varchar(32) not null default 'morning',
    -- morning         通用晨间
    -- weekend         周末
    -- workday         工作日
    -- solar_term      节气（配合 trigger_term 使用）
    -- festival        节日（配合 trigger_festival 使用）
    -- rain / sunny / cold / hot   天气场景
    trigger_term     varchar(16),               -- 命中哪个节气才启用，如 '立春'、'冬至'
    trigger_festival varchar(32),               -- 命中哪个节日才启用，如 '春节'、'中秋'
    weight      integer     not null default 10, -- 权重，越大越容易被抽中
    enabled     boolean     not null default true,
    created_at  timestamptz not null default now(),
    constraint greetings_content_uq unique (content)
);

create index if not exists greetings_category_idx on public.greetings (category, enabled);

comment on table public.greetings is '敬语问候语料库，按场景分类加权随机抽取';

-- -----------------------------------------------------------------------------
-- 2. 节假日 / 调休 / 法定节日
--    day_type 逻辑（后端 holiday.py 实现）：
--      kind = 'holiday'        -> 法定放假（覆盖周末判断）
--      kind = 'makeup_workday' -> 调休补班（覆盖周末判断，优先级最高）
--      kind = 'traditional'    -> 农历/传统节日（不一定放假，仅展示）
--      kind = 'solar_festival' -> 公历节日（不一定放假，仅展示）
--    未命中任何记录时：周六周日 = 休息日，其余 = 工作日
-- -----------------------------------------------------------------------------
create table if not exists public.holidays (
    id          bigserial primary key,
    day         date        not null,
    name        varchar(64) not null,
    kind        varchar(24) not null,
    is_day_off  boolean,
    remark      text,
    created_at  timestamptz not null default now(),
    constraint holidays_day_uq unique (day)
);

create index if not exists holidays_day_idx on public.holidays (day);

comment on table public.holidays is '节假日与调休配置，需按国务院年度公告每年更新一次';
comment on column public.holidays.is_day_off is 'true=放假 false=补班 null=仅展示不影响作息判断';

-- -----------------------------------------------------------------------------
-- 3. 天气缓存（避免每次打开小程序都打第三方 API）
-- -----------------------------------------------------------------------------
create table if not exists public.weather_cache (
    id          bigserial primary key,
    cache_key   varchar(160) not null,
    payload     jsonb        not null,
    fetched_at  timestamptz  not null default now(),
    expire_at   timestamptz  not null,
    constraint weather_cache_key_uq unique (cache_key)
);

create index if not exists weather_cache_expire_idx on public.weather_cache (expire_at);

comment on table public.weather_cache is '第三方天气接口结果缓存，key 形如 now:宁波:2026-09-10';

-- 清理过期缓存（可选：配 pg_cron 每日执行）
-- delete from public.weather_cache where expire_at < now() - interval '1 day';

-- -----------------------------------------------------------------------------
-- 4. 小程序用户（二期：wx.login 换取 openid 后写入）
-- -----------------------------------------------------------------------------
create table if not exists public.wx_users (
    id          bigserial primary key,
    openid      varchar(64) not null,
    nickname    varchar(128),
    avatar_url  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),
    constraint wx_users_openid_uq unique (openid)
);

-- -----------------------------------------------------------------------------
-- 5. 用户偏好（城市、问候风格）
-- -----------------------------------------------------------------------------
create table if not exists public.user_settings (
    id             bigserial primary key,
    openid         varchar(64) not null,
    city_name      varchar(64) not null default '宁波',
    city_id        varchar(32),                 -- 和风天气 location id，缓存下来省一次 geo 查询
    lat            double precision,
    lon            double precision,
    tone           varchar(24) not null default 'classic',  -- classic 典雅 / warm 亲切 / zen 禅意
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    constraint user_settings_openid_uq unique (openid)
);

-- =============================================================================
-- 种子数据：敬语语料
-- =============================================================================
insert into public.greetings (content, category, weight) values
    ('晨安。愿你今日心无挂碍，步履从容。', 'morning', 10),
    ('早安。新的一天，愿所遇皆温柔，所行皆坦途。', 'morning', 10),
    ('清晨吉祥。愿你今日诸事顺遂，喜乐安康。', 'morning', 10),
    ('早安。愿你被这个世界温柔以待，也温柔待人。', 'morning', 9),
    ('晨光微熹，万物可爱。愿你今日平安喜乐。', 'morning', 9),
    ('早安。一日之计在于晨，愿你今日不负时光。', 'morning', 8),
    ('晨安。愿你今日所思皆成，所行皆顺。', 'morning', 8),
    ('早上好。愿你保持热爱，奔赴山海。', 'morning', 8),
    ('晨起安康。愿你今日有清风相伴，有暖阳相随。', 'morning', 7),
    ('早安。愿你的努力都被看见，你的善良都被珍惜。', 'morning', 7),
    ('晨安。世间万物皆有定时，愿你不慌不忙，静待花开。', 'morning', 6),
    ('早安。愿你今日心境明朗，如这清晨的光。', 'morning', 6),
    ('周末愉快。愿你慢下来，好好陪陪自己和家人。', 'weekend', 10),
    ('早安。难得的休息日，愿你睡到自然醒，心满意足。', 'weekend', 9),
    ('周末晨安。愿你把时间还给自己，做喜欢的事。', 'weekend', 8),
    ('早安，新的一周开始了。愿你元气满满，稳稳向前。', 'workday', 10),
    ('晨安。工作日也要好好照顾自己，记得吃早餐。', 'workday', 9),
    ('早安。愿你今日事少心轻，效率自来。', 'workday', 8),
    ('晨安。忙碌之余，别忘了抬头看看天。', 'workday', 7)
on conflict (content) do nothing;

insert into public.greetings (content, category, trigger_term, weight) values
    ('立春了。愿你新的一年，如春风般舒展自在。', 'solar_term', '立春', 10),
    ('雨水至。愿这场春雨，润泽你一整年的好心情。', 'solar_term', '雨水', 8),
    ('惊蛰了。愿你沉睡的梦想，也随春雷一同醒来。', 'solar_term', '惊蛰', 8),
    ('春分。昼夜均分，愿你生活也平衡安稳。', 'solar_term', '春分', 8),
    ('清明。愿你在追思中，更懂珍惜眼前人。', 'solar_term', '清明', 8),
    ('谷雨。春将尽，愿你抓住最后一抹春色。', 'solar_term', '谷雨', 7),
    ('立夏了。愿你如夏木般繁茂，向阳而生。', 'solar_term', '立夏', 8),
    ('小满。小得盈满，愿你知足常乐，恰到好处。', 'solar_term', '小满', 8),
    ('芒种。有收有种，愿你忙而不茫，心生欢喜。', 'solar_term', '芒种', 8),
    ('夏至。白昼最长的一天，愿你的好心情也最长。', 'solar_term', '夏至', 8),
    ('小暑。温风渐至，愿你心有清凉，不躁不烦。', 'solar_term', '小暑', 7),
    ('大暑。一年最热时，愿你心静自然凉，安然度夏。', 'solar_term', '大暑', 8),
    ('立秋了。夏日的遗憾，愿被秋风温柔化解。', 'solar_term', '立秋', 8),
    ('处暑。暑气至此而止，愿你日渐从容清爽。', 'solar_term', '处暑', 7),
    ('白露。天凉了，记得添件衣裳。', 'solar_term', '白露', 8),
    ('秋分。昼夜再均分，愿你收获满满。', 'solar_term', '秋分', 7),
    ('寒露。露寒而凝，愿你有人牵挂，有处可归。', 'solar_term', '寒露', 8),
    ('霜降。秋意浓，愿你心暖人不寒。', 'solar_term', '霜降', 7),
    ('立冬了。万物收藏，愿你养精蓄锐，静待来春。', 'solar_term', '立冬', 8),
    ('小雪。天渐寒，愿有人问你粥可温。', 'solar_term', '小雪', 8),
    ('大雪。愿你心有暖意，不惧这漫天风雪。', 'solar_term', '大雪', 7),
    ('冬至。昼最短，夜最长，愿你被温暖包围。', 'solar_term', '冬至', 10),
    ('小寒。一年最冷时，愿你有人暖，有事盼。', 'solar_term', '小寒', 8),
    ('大寒。冬将尽，春不远，愿你不畏严寒，静候花开。', 'solar_term', '大寒', 8)
on conflict (content) do nothing;

insert into public.greetings (content, category, trigger_festival, weight) values
    ('新春吉祥。愿你岁岁常欢愉，年年皆胜意。', 'festival', '春节', 10),
    ('元宵安康。愿你团团圆圆，甜甜蜜蜜。', 'festival', '元宵节', 9),
    ('端午安康。愿你驱邪避疫，平安顺遂。', 'festival', '端午节', 9),
    ('中秋快乐。愿人月两团圆，千里共婵娟。', 'festival', '中秋节', 10),
    ('重阳安康。愿长辈健康长寿，岁月不老。', 'festival', '重阳节', 8),
    ('元旦快乐。新岁启封，愿你所求皆如愿，所行化坦途。', 'festival', '元旦', 10),
    ('新年首日，晨安。愿你这一年，平安喜乐，诸事顺遂。', 'festival', '元旦', 8),
    ('清明安康。愿你在追思中，更懂珍惜眼前人。', 'festival', '清明节', 9),
    ('清明。愿逝者安息，生者安康，人间皆安好。', 'festival', '清明节', 8),
    ('劳动节快乐。愿你劳有所获，忙有所值，不负辛苦。', 'festival', '劳动节', 9),
    ('五一安康。愿你在忙碌之外，也有属于自己的清闲。', 'festival', '劳动节', 8),
    ('国庆快乐。愿山河锦绣，国泰民安，你我皆安好。', 'festival', '国庆节', 10),
    ('十一长假，晨安。愿你在这段日子里，好好歇一歇。', 'festival', '国庆节', 9)
on conflict (content) do nothing;

insert into public.greetings (content, category, weight) values
    ('今日有雨，路滑慢行。愿你带伞出门，也带好心情。', 'rain', 10),
    ('雨天早安。愿你心晴，便不惧天阴。', 'rain', 9),
    ('天朗气清，惠风和畅。愿你不负这好天气。', 'sunny', 10),
    ('阳光正好，早安。愿你今日也闪闪发光。', 'sunny', 9),
    ('降温了，早安。记得添衣保暖，别让自己受凉。', 'cold', 10),
    ('天气转凉，愿你有衣暖身，有人暖心。', 'cold', 9),
    ('今日炎热，早安。愿你心静自然凉，多喝水。', 'hot', 10),
    ('酷暑难当，愿你寻得一处清凉，安放身心。', 'hot', 8)
on conflict (content) do nothing;

-- =============================================================================
-- 种子数据：2026 年节假日与调休（已按国务院办公厅 2025-11-04 公告录全）
--   依据：《国务院办公厅关于 2026 年部分节假日安排的通知》
--   元旦 1/1-1/3，春节 2/15-2/23，清明 4/4-4/6，劳动 5/1-5/5，
--   端午 6/19-6/21，中秋 9/25-9/27，国庆 10/1-10/7
--
-- ⚠️ 每年 11 月左右国务院会发布次年安排，调休细则每年都变，到时整段重跑即可：
--    https://www.gov.cn/zhengce/content/   （搜索「20XX年部分节假日安排的通知」）
--
-- 写法采用 on conflict (day) do update，重跑新一年的数据时会覆盖旧记录，
-- 而不是「do nothing」那样静默跳过导致数据过期。
-- =============================================================================
insert into public.holidays (day, name, kind, is_day_off, remark) values
    -- 元旦：1/1(周四)-1/3(周六) 放假，1/4(周日) 上班
    ('2026-01-01', '元旦',         'holiday',        true,  '元旦假期第1天'),
    ('2026-01-02', '元旦',         'holiday',        true,  '元旦假期第2天'),
    ('2026-01-03', '元旦',         'holiday',        true,  '元旦假期第3天'),
    ('2026-01-04', '元旦调休补班', 'makeup_workday', false, '1月4日(周日)上班'),
    -- 春节：2/15(腊月廿八)-2/23(正月初七) 放假，2/14、2/28 上班
    ('2026-02-14', '春节调休补班', 'makeup_workday', false, '2月14日(周六)上班'),
    ('2026-02-15', '春节',         'holiday',        true,  '春节假期第1天·腊月廿八'),
    ('2026-02-16', '春节',         'holiday',        true,  '春节假期第2天·除夕'),
    ('2026-02-17', '春节',         'holiday',        true,  '春节假期第3天·正月初一'),
    ('2026-02-18', '春节',         'holiday',        true,  '春节假期第4天'),
    ('2026-02-19', '春节',         'holiday',        true,  '春节假期第5天'),
    ('2026-02-20', '春节',         'holiday',        true,  '春节假期第6天'),
    ('2026-02-21', '春节',         'holiday',        true,  '春节假期第7天'),
    ('2026-02-22', '春节',         'holiday',        true,  '春节假期第8天'),
    ('2026-02-23', '春节',         'holiday',        true,  '春节假期第9天·正月初七'),
    ('2026-02-28', '春节调休补班', 'makeup_workday', false, '2月28日(周六)上班'),
    -- 清明：4/4(周六)-4/6(周一) 放假，不调休
    ('2026-04-04', '清明节',       'holiday',        true,  '清明假期第1天'),
    ('2026-04-05', '清明节',       'holiday',        true,  '清明假期第2天'),
    ('2026-04-06', '清明节',       'holiday',        true,  '清明假期第3天'),
    -- 劳动节：5/1(周五)-5/5(周二) 放假，5/9(周六) 上班
    ('2026-05-01', '劳动节',       'holiday',        true,  '劳动节假期第1天'),
    ('2026-05-02', '劳动节',       'holiday',        true,  '劳动节假期第2天'),
    ('2026-05-03', '劳动节',       'holiday',        true,  '劳动节假期第3天'),
    ('2026-05-04', '劳动节',       'holiday',        true,  '劳动节假期第4天'),
    ('2026-05-05', '劳动节',       'holiday',        true,  '劳动节假期第5天'),
    ('2026-05-09', '劳动节调休补班', 'makeup_workday', false, '5月9日(周六)上班'),
    -- 端午：6/19(周五)-6/21(周日) 放假，不调休
    ('2026-06-19', '端午节',       'holiday',        true,  '端午假期第1天'),
    ('2026-06-20', '端午节',       'holiday',        true,  '端午假期第2天'),
    ('2026-06-21', '端午节',       'holiday',        true,  '端午假期第3天'),
    -- 中秋：9/25(周五)-9/27(周日) 放假，不调休
    ('2026-09-25', '中秋节',       'holiday',        true,  '中秋假期第1天'),
    ('2026-09-26', '中秋节',       'holiday',        true,  '中秋假期第2天'),
    ('2026-09-27', '中秋节',       'holiday',        true,  '中秋假期第3天'),
    -- 国庆：10/1(周四)-10/7(周三) 放假，9/20、10/10 上班
    ('2026-09-20', '国庆调休补班', 'makeup_workday', false, '9月20日(周日)上班'),
    ('2026-10-01', '国庆节',       'holiday',        true,  '国庆假期第1天'),
    ('2026-10-02', '国庆节',       'holiday',        true,  '国庆假期第2天'),
    ('2026-10-03', '国庆节',       'holiday',        true,  '国庆假期第3天'),
    ('2026-10-04', '国庆节',       'holiday',        true,  '国庆假期第4天'),
    ('2026-10-05', '国庆节',       'holiday',        true,  '国庆假期第5天'),
    ('2026-10-06', '国庆节',       'holiday',        true,  '国庆假期第6天'),
    ('2026-10-07', '国庆节',       'holiday',        true,  '国庆假期第7天'),
    ('2026-10-10', '国庆调休补班', 'makeup_workday', false, '10月10日(周六)上班'),
    -- 仅展示、不影响作息判断的节日
    ('2026-03-08', '妇女节',       'solar_festival', null,  '部分人群放假，仅展示'),
    ('2026-06-01', '儿童节',       'solar_festival', null,  '仅展示')
on conflict (day) do update set
    name       = excluded.name,
    kind       = excluded.kind,
    is_day_off = excluded.is_day_off,
    remark     = excluded.remark;

-- =============================================================================
-- 数据完整性：约束 kind 取值，避免手抖写错导致后端 day_type 判断失效
-- =============================================================================
do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'holidays_kind_chk' and conrelid = 'public.holidays'::regclass
    ) then
        alter table public.holidays
            add constraint holidays_kind_chk
            check (kind in ('holiday', 'makeup_workday', 'traditional', 'solar_festival'));
    end if;
end $$;

-- =============================================================================
-- 安全加固（可选，推荐执行）
--   后端 FastAPI 用 postgres 角色直连，该角色带 BYPASSRLS，开启后读写不受任何影响；
--   但能彻底堵死 anon / authenticated 角色经 PostgREST(supabase-js) 裸读这些表。
--   若将来要用 anon key 从前端直连，需先给对应表补 policy，否则查询会返回空。
-- =============================================================================
-- alter table public.greetings      enable row level security;
-- alter table public.holidays       enable row level security;
-- alter table public.weather_cache  enable row level security;
-- alter table public.wx_users       enable row level security;
-- alter table public.user_settings  enable row level security;

-- =============================================================================
-- 执行后自检（可单独跑）
--   select count(*) from public.greetings where enabled;                 -- 应 >= 50
--   select count(*) from public.holidays  where is_day_off is not null;  -- 应 >= 40
--   select day, name, kind, is_day_off from public.holidays
--       where day between '2026-09-20' and '2026-10-10' order by day;
-- =============================================================================
