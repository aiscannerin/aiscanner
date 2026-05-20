import client from './client'

export const apiGetPlans          = ()       => client.get('/plans')
export const apiCreateOrder       = (body)   => client.post('/payments/create-order', body)
export const apiVerifyPayment     = (body)   => client.post('/payments/verify-payment', body)
export const apiGetPaymentHistory = ()       => client.get('/payments/history')
export const apiGetCurrentSub     = ()       => client.get('/subscriptions/current')
