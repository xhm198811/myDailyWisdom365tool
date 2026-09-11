const {
  apiOrigin,
  apiPrefix,
  channel,
  cloudEnv,
  cloudService,
  requestTimeout,
} = require('../config')

/** 统一把响应体转成 resolve / reject，两种通道共用 */
function handleResponse(res, resolve, reject) {
  const body = res.data
  if (res.statusCode === 200 && body && body.ok) {
    resolve(body)
  } else {
    const msg = (body && body.detail) || `HTTP ${res.statusCode}`
    reject(new Error(msg))
  }
}

/** 通道一：wx.request 直连（本地开发 / 局域网联调） */
function httpRequest(path, data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: apiOrigin + apiPrefix + path,
      data,
      method: 'GET',
      timeout: requestTimeout,
      header: { 'content-type': 'application/json' },
      success: (res) => handleResponse(res, resolve, reject),
      fail: (err) => reject(new Error(err.errMsg || 'network error')),
    })
  })
}

/**
 * 通道二：wx.cloud.callContainer 走微信私有协议调用云托管服务。
 * 不需要配置 request 合法域名、不需要域名备案，正式发布用这条。
 * 注意 path 要带完整前缀（/api/v1/xxx），服务名通过 X-WX-SERVICE 头指定。
 */
function containerRequest(path, data) {
  return new Promise((resolve, reject) => {
    if (!cloudEnv || !cloudService) {
      reject(new Error('cloudEnv / cloudService 未配置，请检查 config.js'))
      return
    }
    wx.cloud.callContainer({
      config: { env: cloudEnv },
      path: apiPrefix + path,
      method: 'GET',
      data,
      timeout: requestTimeout,
      header: {
        'X-WX-SERVICE': cloudService,
        'content-type': 'application/json',
      },
      success: (res) => handleResponse(res, resolve, reject),
      fail: (err) => reject(new Error(err.errMsg || 'callContainer error')),
    })
  })
}

function request(path, data = {}) {
  if (channel === 'container') return containerRequest(path, data)
  return httpRequest(path, data)
}

/** 今日聚合数据：日期 + 天气 + 敬语 */
function getToday(params = {}) {
  return request('/today', params)
}

/** 换一句敬语 */
function randomGreeting(params = {}) {
  return request('/greeting/random', params)
}

/** 某年节气表 */
function getCalendar(year) {
  return request('/calendar', { year })
}

/** 健康检查 */
function health() {
  return request('/health')
}

module.exports = { request, getToday, randomGreeting, getCalendar, health }
