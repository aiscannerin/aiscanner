import client from './client'

export const apiGetAlertSettings    = ()       => client.get('/alert-settings')
export const apiUpdateAlertSettings = (body)   => client.patch('/alert-settings', body)
