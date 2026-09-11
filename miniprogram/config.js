// 环境配置
// ------------------------------------------------------------------
// 两种调用通道，由 channel 决定：
//
// 1) 'http' —— wx.request 直连后端，本地开发和真机联调用。
//    开发者工具需在「详情 -> 本地设置」勾选
//    「不校验合法域名、web-view、TLS 版本以及 HTTPS 证书」。
//    真机调试不能用 127.0.0.1，要填电脑局域网 IP（如 http://192.168.1.20:8123）。
//
// 2) 'container' —— wx.cloud.callContainer 走微信私有协议调用云托管服务。
//    ✅ 正式发布用这个，理由：
//       - 官方文档明确：用云托管作后端可无需配置通讯域名
//       - 无需域名 ICP 备案、无需自备 HTTPS 证书
//       - 云托管默认域名 *.app.tcloudbase.com 未备案，填不进白名单，wx.request 走不通
//    前提：小程序与云托管环境属同一主体，基础库 >= 2.23.0
// ------------------------------------------------------------------
const ENV = 'dev' // ← 上线前改成 'prod'

const CONFIG = {
  dev: {
    channel: 'http',
    // 开发者工具可填 127.0.0.1；真机请改成电脑局域网 IP
    apiOrigin: 'http://127.0.0.1:8123',
    apiPrefix: '/api/v1',
    cloudEnv: '',
    cloudService: '',
    requestTimeout: 10000,
  },
  prod: {
    channel: 'container',
    apiOrigin: '', // container 模式下不使用
    apiPrefix: '/api/v1',
    cloudEnv: 'prod-xxxxxxxx', // ← 云托管「环境 ID」，控制台环境概览可查
    cloudService: 'greeting-api', // ← 云托管「服务名称」，建服务时自己起的名
    requestTimeout: 10000,
  },
}

module.exports = {
  env: ENV,
  defaultCity: '宁波',
  ...CONFIG[ENV],
}
