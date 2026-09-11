const api = require('../../utils/api')
const { weatherEmoji, timeGreeting } = require('../../utils/format')
const { defaultCity } = require('../../config')

const CACHE_KEY = 'last_today_payload'
const CITY_KEY = 'user_city'

Page({
  data: {
    loading: true,
    refreshing: false,
    greetingLoading: false,
    errorText: '',
    stale: false, // true 表示当前展示的是本地缓存
    city: defaultCity,
    timeGreet: '',
    day: null,
    weather: null,
    greeting: null,
    degraded: [],
    degradedText: '',
  },

  onLoad() {
    const city = wx.getStorageSync(CITY_KEY) || defaultCity
    this.setData({ city })

    // 先渲染本地缓存，避免白屏，再静默刷新
    const cached = wx.getStorageSync(CACHE_KEY)
    if (cached) this.applyPayload(cached, true)

    this.load()
  },

  onPullDownRefresh() {
    this.load(true)
  },

  onShareAppMessage() {
    const g = this.data.greeting
    return {
      title: g ? g.content : '晨间问候',
      path: '/pages/index/index',
    }
  },

  async load(isPull) {
    if (isPull) this.setData({ refreshing: true })
    else this.setData({ loading: true })

    try {
      const res = await api.getToday({ city: this.data.city })
      wx.setStorageSync(CACHE_KEY, res)
      this.applyPayload(res, false)
      this.setData({ errorText: '', stale: false })
    } catch (err) {
      const cached = wx.getStorageSync(CACHE_KEY)
      if (cached) {
        this.applyPayload(cached, true)
        this.setData({ errorText: '网络异常，展示上次数据' })
      } else {
        this.setData({
          errorText: `加载失败：${err.message || err.errMsg || '未知错误'}`,
        })
      }
    } finally {
      this.setData({ loading: false, refreshing: false })
      if (isPull) wx.stopPullDownRefresh()
    }
  },

  /** 把后端返回摊平成 WXML 好用的结构 */
  applyPayload(res, stale) {
    const d = res.data.date
    const w = res.data.weather
    const g = res.data.greeting
    const degraded = res.degraded || []

    const degradedMap = {
      database: '数据库未连接',
      weather: '天气为示例数据',
    }

    this.setData({
      stale: !!stale,
      day: {
        year: d.solar.year,
        month: d.solar.month,
        day: d.solar.day,
        weekday: d.weekday,
        lunarMonthCn: d.lunar.month_cn,
        lunarDayCn: d.lunar.day_cn,
        lunarYearCn: d.lunar.year_cn,
        zodiac: d.lunar.zodiac,
        ganzhiDay: d.ganzhi_day,
        festivals: d.festivals || [],
        solarTerm: d.solar_term,
        dayType: d.day_type,
        dayTypeLabel: d.day_type_label,
        nextSolarTerm: d.next_solar_term,
        nextHoliday: d.next_holiday,
      },
      weather: {
        city: w.city,
        iconEmoji: weatherEmoji(w.icon),
        text: w.text,
        temp: w.temp,
        feelsLike: w.feels_like,
        tempMin: w.temp_min,
        tempMax: w.temp_max,
        humidity: w.humidity,
        windDir: w.wind_dir,
        windScale: w.wind_scale,
        aqi: w.aqi,
        aqiCategory: w.aqi_category,
        tips: w.tips,
        source: w.source,
      },
      greeting: g,
      degraded,
      degradedText: degraded.map((k) => degradedMap[k] || k).join(' · '),
      timeGreet: timeGreeting(new Date().getHours()),
    })
  },

  async onRefreshGreeting() {
    if (this.data.greetingLoading) return
    this.setData({ greetingLoading: true })
    wx.vibrateShort && wx.vibrateShort({ type: 'light' })
    try {
      const res = await api.randomGreeting({ city: this.data.city })
      this.setData({ greeting: res.data })
    } catch (err) {
      wx.showToast({ title: '换一句失败', icon: 'none' })
    } finally {
      this.setData({ greetingLoading: false })
    }
  },

  onChooseCity() {
    wx.showModal({
      title: '切换城市',
      editable: true,
      placeholderText: '输入城市名，如 宁波',
      content: this.data.city,
      success: (r) => {
        if (r.confirm && r.content && r.content.trim()) {
          const city = r.content.trim()
          wx.setStorageSync(CITY_KEY, city)
          this.setData({ city })
          this.load()
        }
      },
    })
  },
})
