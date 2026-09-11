const { defaultCity, channel, cloudEnv } = require('./config')

App({
  globalData: {
    city: defaultCity,
  },

  onLaunch() {
    // 走云托管通道时必须先初始化，否则 wx.cloud.callContainer 不可用
    if (channel === 'container') {
      if (!wx.cloud) {
        console.error('[app] 当前基础库不支持 wx.cloud，请调高基础库版本（>= 2.23.0）')
      } else {
        wx.cloud.init({ env: cloudEnv, traceUser: false })
        console.log('[app] cloud container mode, env =', cloudEnv)
      }
    }

    // 冷启动时预热一次，让首屏更快
    const city = wx.getStorageSync('user_city')
    if (city) this.globalData.city = city

    const info = wx.getSystemInfoSync()
    console.log('[app] launch', info.platform, info.version)
  },
})
