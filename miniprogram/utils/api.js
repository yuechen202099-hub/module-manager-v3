const { getApiBaseUrl } = require('./config')
const { getToken } = require('./session')

function unwrapResponse(response) {
  const body = response.data || {}
  if (response.statusCode < 200 || response.statusCode >= 300) {
    const message = body.detail || body.message || (body.error && body.error.message) || `请求失败 ${response.statusCode}`
    throw new Error(message)
  }
  if (body.error) {
    throw new Error(body.error.message || body.error.code || '请求失败')
  }
  return body.data
}

function requestErrorMessage(error, fallback) {
  const message = (error && error.errMsg) || ''
  if (message.indexOf('timeout') >= 0) return '网络超时，请稍后重试'
  if (message.indexOf('fail') >= 0 || message.indexOf('ERR_') >= 0) return fallback
  return message || fallback
}

function request(path, options = {}) {
  const token = getToken()
  const headers = Object.assign({}, options.header || {})
  if (token) headers.Authorization = `bearer ${token}`
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${getApiBaseUrl()}${path}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: headers,
      success(response) {
        try {
          resolve(unwrapResponse(response))
        } catch (error) {
          reject(error)
        }
      },
      fail(error) {
        reject(new Error(requestErrorMessage(error, '网络连接失败，请稍后重试')))
      }
    })
  })
}

function uploadFile(path, filePath, formData = {}) {
  const token = getToken()
  const header = token ? { Authorization: `bearer ${token}` } : {}
  return new Promise((resolve, reject) => {
    wx.uploadFile({
      url: `${getApiBaseUrl()}${path}`,
      filePath,
      name: 'file',
      formData,
      header,
      success(response) {
        try {
          const parsed = JSON.parse(response.data || '{}')
          resolve(unwrapResponse({ statusCode: response.statusCode, data: parsed }))
        } catch (error) {
          reject(error)
        }
      },
      fail(error) {
        reject(new Error(requestErrorMessage(error, '上传失败，请稍后重试')))
      }
    })
  })
}

module.exports = {
  request,
  uploadFile
}
