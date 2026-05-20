import client from './client'

export function apiLogin({ email, password }) {
  return client.post('/auth/login', { email, password })
}

export function apiGetMe() {
  return client.get('/auth/me')
}

export function apiRegister(payload) {
  return client.post('/auth/register', payload)
}

export function apiSendOtp({ email, purpose }) {
  return client.post('/auth/send-otp', { email, purpose })
}

export function apiVerifyOtp({ email, otp, purpose }) {
  return client.post('/auth/verify-otp', { email, otp, purpose })
}

export function apiForgotPassword({ email }) {
  return client.post('/auth/forgot-password', { email })
}

// reset_token comes from verify-otp (forgot_password purpose); new_password must
// pass backend validate_password (min 8 chars + 1 uppercase + 1 number).
export function apiResetPassword({ reset_token, new_password }) {
  return client.post('/auth/reset-password', { reset_token, new_password })
}
