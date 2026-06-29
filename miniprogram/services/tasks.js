const { request } = require('../utils/api')

function fetchTasks() {
  return request('/miniprogram/tasks').then((data) => data.items || [])
}

module.exports = {
  fetchTasks
}
