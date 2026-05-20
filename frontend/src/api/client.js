/**
 * Axios client
 * ============
 * baseURL resolution (in priority order):
 *   1. VITE_API_URL env var  — set in .env / .env.production
 *   2. '/api'                — relative, works through Vite dev-server proxy
 *                              and any reverse-proxy in production
 *
 * Do NOT hardcode 'http://localhost:3010/api' here.
 * That bypasses the Vite proxy, breaks cross-origin preflight in some
 * environments, and silently fails in production.
 */
import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || '/api'

const client = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 10000,
})

// ── Request interceptor ──────────────────────────────────────────────────────
// Attach the access token from localStorage on every outgoing request.
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// ── Response interceptor ─────────────────────────────────────────────────────
// On 401: attempt a silent token refresh using the stored refresh_token.
// If refresh succeeds   → retry the original request with the new token.
// If refresh fails      → clear tokens and redirect to /login.
//
// A "_retry" flag prevents infinite loops when the /auth/refresh call itself
// returns 401 (i.e. the refresh token is also expired/revoked).

let _isRefreshing  = false
let _pendingQueue  = []   // [{ resolve, reject }]

function _processPending(error, token = null) {
  _pendingQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error)
    else       resolve(token)
  })
  _pendingQueue = []
}

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config

    // Only handle 401 errors that haven't already been retried,
    // and that are NOT coming from the refresh endpoint itself
    // (to avoid infinite recursion).
    if (
      error.response?.status !== 401 ||
      original._retry ||
      original.url === '/auth/refresh'
    ) {
      return Promise.reject(error)
    }

    const refreshToken = localStorage.getItem('refresh_token')
    if (!refreshToken) {
      // No refresh token → immediate logout
      _handleForcedLogout()
      return Promise.reject(error)
    }

    // Mark this request so we don't retry it a second time
    original._retry = true

    if (_isRefreshing) {
      // Another request already triggered a refresh — queue this one
      return new Promise((resolve, reject) => {
        _pendingQueue.push({ resolve, reject })
      }).then((newToken) => {
        original.headers.Authorization = `Bearer ${newToken}`
        return client(original)
      })
    }

    _isRefreshing = true

    try {
      const res = await client.post('/auth/refresh', { refresh_token: refreshToken })
      const { access_token, refresh_token: newRefresh } = res.data?.data ?? {}

      if (!access_token) throw new Error('No access_token in refresh response')

      // Persist new tokens
      localStorage.setItem('access_token', access_token)
      if (newRefresh) localStorage.setItem('refresh_token', newRefresh)

      // Unblock any queued requests
      _processPending(null, access_token)

      // Retry the original failed request
      original.headers.Authorization = `Bearer ${access_token}`
      return client(original)
    } catch (refreshError) {
      _processPending(refreshError)
      _handleForcedLogout()
      return Promise.reject(refreshError)
    } finally {
      _isRefreshing = false
    }
  },
)

function _handleForcedLogout() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  // Navigate without React Router to break out of any component tree
  if (window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

export default client
