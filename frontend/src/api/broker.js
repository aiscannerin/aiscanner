import client from './client'

/**
 * Per-user broker (Dhan) API credential management.
 * The access token is never returned by the backend — only connection status.
 */
export const brokerApi = {
  // Current Dhan connection status (connected / valid / last error)
  getDhanStatus: () => client.get('/broker/dhan'),

  // Save or update credentials. body = { client_id, access_token }
  saveDhan: (body) => client.put('/broker/dhan', body, { timeout: 30000 }),

  // Re-validate stored credentials against Dhan
  testDhan: () => client.post('/broker/dhan/test', {}, { timeout: 30000 }),

  // Disconnect (delete stored credentials)
  deleteDhan: () => client.delete('/broker/dhan'),
}
