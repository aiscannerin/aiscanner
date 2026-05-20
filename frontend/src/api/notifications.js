import client from './client'

export const apiGetNotifications = ()   => client.get('/notifications/recent')
export const apiMarkRead         = (id) => client.post(`/notifications/${id}/read`)
export const apiMarkAllRead      = ()   => client.post('/notifications/read-all')
