const SESSION_KEY = 'constructionSession:v1'

function getSession() {
  return wx.getStorageSync(SESSION_KEY) || null
}

function getToken() {
  const session = getSession()
  return session && session.accessToken ? session.accessToken : ''
}

function setSession(payload) {
  const session = {
    accessToken: payload.access_token || payload.accessToken || '',
    tokenType: payload.token_type || payload.tokenType || 'bearer',
    openid: payload.openid || '',
    user: payload.user || null,
    teamId: payload.team_id || payload.teamId || ''
  }
  wx.setStorageSync(SESSION_KEY, session)
  return session
}

function clearSession() {
  wx.removeStorageSync(SESSION_KEY)
}

function requireSession() {
  const session = getSession()
  if (!session || !session.accessToken) {
    wx.reLaunch({ url: '/pages/login/index' })
    return null
  }
  return session
}

module.exports = {
  SESSION_KEY,
  getSession,
  getToken,
  setSession,
  clearSession,
  requireSession
}
