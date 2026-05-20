import { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { apiGetMe } from '../api/auth'

const AuthCtx = createContext(null)

/**
 * A real JWT has exactly 3 base64url segments separated by dots.
 * Guards against undefined / "undefined" / partial strings in localStorage.
 */
function isValidJwtShape(token) {
  if (!token || typeof token !== 'string') return false
  return token.split('.').length === 3
}

function getStoredTokens() {
  return {
    accessToken:  localStorage.getItem('access_token'),
    refreshToken: localStorage.getItem('refresh_token'),
  }
}

function storeTokens(access, refresh) {
  localStorage.setItem('access_token', access)
  if (refresh) localStorage.setItem('refresh_token', refresh)
}

function clearTokens() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
}

/**
 * Extract the user object from an /api/auth/me axios response.
 *
 * Backend envelope: { success, message, data: { id, full_name, email, ... } }
 * So: axiosResponse.data.data  === user object
 */
function parseUserFromMeResponse(axiosData) {
  if (import.meta.env.DEV) {
    // Log shape without printing any token value
    console.debug('[Auth /me] response keys:', Object.keys(axiosData ?? {}))
    console.debug('[Auth /me] data keys:',     Object.keys(axiosData?.data ?? {}))
  }
  // axiosData = response.data (axios already unwraps .data once)
  // envelope.data is the user object
  return axiosData?.data ?? null
}

export function AuthProvider({ children }) {
  const [user,    setUser]    = useState(null)
  const [loading, setLoading] = useState(true)

  // Restore session on mount — only if a valid-shaped JWT exists
  useEffect(() => {
    const { accessToken } = getStoredTokens()

    if (import.meta.env.DEV) {
      console.debug('[Auth] token exists:', !!accessToken)
      if (accessToken) {
        console.debug('[Auth] token segment count:', accessToken.split('.').length)
      }
    }

    if (!isValidJwtShape(accessToken)) {
      if (accessToken) {
        console.debug('[Auth] stored token has invalid shape — clearing')
        clearTokens()
      }
      setLoading(false)
      return
    }

    apiGetMe()
      .then(({ data: axiosData }) => {
        const user = parseUserFromMeResponse(axiosData)
        if (user) {
          setUser(user)
        } else {
          console.debug('[Auth] /me returned no user object — clearing tokens')
          clearTokens()
        }
      })
      .catch(() => {
        console.debug('[Auth] /me rejected — clearing tokens')
        clearTokens()
      })
      .finally(() => setLoading(false))
  }, [])

  const login = useCallback((accessToken, refreshToken, userData) => {
    storeTokens(accessToken, refreshToken)
    setUser(userData)
  }, [])

  const logout = useCallback(() => {
    clearTokens()
    setUser(null)
  }, [])

  return (
    <AuthCtx.Provider value={{ user, loading, login, logout, isAuthenticated: !!user }}>
      {children}
    </AuthCtx.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthCtx)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
