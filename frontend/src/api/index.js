import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000
})

// 生成用户ID（每个浏览器会话唯一）
const getUserId = () => {
  let userId = sessionStorage.getItem('labeler_user_id')
  if (!userId) {
    userId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9)
    sessionStorage.setItem('labeler_user_id', userId)
  }
  return userId
}

export const userId = getUserId()

// 图片相关
export const getImages = () => api.get('/images', { params: { user_id: userId } })
export const getImageUrl = (filename) => `/api/images/${encodeURIComponent(filename)}`
export const getLabeledImageUrl = (filename) => `/api/labeled-images/${encodeURIComponent(filename)}`

// 标注相关
export const getLabels = (page = 1, perPage = 50) =>
  api.get('/labels', { params: { page, per_page: perPage } })
export const getLabel = (id) => api.get(`/labels/${id}`)
export const createLabel = (data) => api.post('/labels', data)
export const updateLabel = (id, data) => api.put(`/labels/${id}`, data)
export const deleteLabel = (id) => api.delete(`/labels/${id}`)
export const exportLabels = () => window.open('/api/labels/export', '_blank')
export const exportYoloLabels = () => window.open('/api/labels/export-yolo', '_blank')

// 航司相关
export const getAirlines = () => api.get('/airlines')
export const createAirline = (data) => api.post('/airlines', data)

// 机型相关
export const getAircraftTypes = () => api.get('/aircraft-types')
export const createAircraftType = (data) => api.post('/aircraft-types', data)

// 统计相关
export const getStats = () => api.get('/stats')

// 锁相关
export const acquireLock = (filename) =>
  api.post('/locks/acquire', { filename, user_id: userId })
export const releaseLock = (filename) =>
  api.post('/locks/release', { filename, user_id: userId })
export const releaseAllLocks = () =>
  api.post('/locks/release-all', { user_id: userId })
export const sendHeartbeat = (filename) =>
  api.post('/locks/heartbeat', { filename, user_id: userId })
export const getLockStatus = (filename) =>
  api.get(`/locks/status/${encodeURIComponent(filename)}`)

export default api
