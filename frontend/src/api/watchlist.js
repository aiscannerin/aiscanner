import client from './client'

export const apiGetWatchlist    = ()         => client.get('/watchlist')
export const apiAddToWatchlist  = (payload)  => client.post('/watchlist', payload)
export const apiRemoveTracked   = (id)       => client.delete(`/watchlist/${id}`)
export const apiUpdateTracked   = (id, body) => client.patch(`/watchlist/${id}`, body)
