import client from './client'

export const apiGetSubscription = () => client.get('/subscriptions/current')
export const apiGetAccessibleTools = () => client.get('/tools/accessible')
export const apiGetRecentScans = () => client.get('/scanners/recent')
