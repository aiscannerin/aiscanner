import { useNavigate } from 'react-router-dom'
import { Zap } from 'lucide-react'
import { Button } from '../components/ui/Button'
import { useAuth } from '../context/AuthContext'
import { useShowToast } from '../context/ToastContext'

export function DashboardPlaceholder() {
  const { user, logout } = useAuth()
  const navigate  = useNavigate()
  const showToast = useShowToast()

  // Prefer full_name → email → fallback
  const displayName = user?.full_name || user?.email || 'User'
  const displaySub  = user?.full_name && user?.email ? user.email : null

  function handleLogout() {
    logout()
    showToast('Logged out successfully', 'success')
    navigate('/', { replace: true })
  }

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-6 gap-6"
      style={{ background: '#050810' }}
    >
      <div className="w-12 h-12 rounded-xl bg-primary-container flex items-center justify-center shadow-glow-btn">
        <Zap size={22} className="text-white" fill="white" />
      </div>

      <div className="text-center">
        <h1 className="text-headline-md text-on-surface mb-1">Dashboard coming soon</h1>
        <p className="text-body-main text-primary font-medium">{displayName}</p>
        {displaySub && (
          <p className="text-body-sm text-outline mt-0.5">{displaySub}</p>
        )}
      </div>

      <div className="flex gap-3">
        <Button variant="ghost" onClick={() => navigate('/')}>← Landing page</Button>
        <Button variant="outline" onClick={handleLogout}>Log out</Button>
      </div>
    </div>
  )
}
