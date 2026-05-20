import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ToastProvider }   from './context/ToastContext'
import { AuthProvider }    from './context/AuthContext'
import { useAuth }         from './context/AuthContext'
import { LandingPage }     from './pages/LandingPage'
import { LoginPage }       from './pages/LoginPage'
import { RegisterPage }    from './pages/RegisterPage'
import DashboardPage         from './pages/DashboardPage'
import ScannerPage           from './pages/ScannerPage'
import MaxPainScannerPage    from './pages/MaxPainScannerPage'
import PricingPage           from './pages/PricingPage'
import SettingsPage          from './pages/SettingsPage'
import ForgotPasswordPage    from './pages/ForgotPasswordPage'
import ResetPasswordPage     from './pages/ResetPasswordPage'
import TermsPage             from './pages/TermsPage'
import PrivacyPage           from './pages/PrivacyPage'
import RiskDisclaimerPage    from './pages/RiskDisclaimerPage'
import SupportPage           from './pages/SupportPage'

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />
  return children
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/"          element={<LandingPage />} />
      <Route path="/login"     element={<LoginPage />} />
      <Route path="/register"  element={<RegisterPage />} />
      <Route path="/dashboard"                 element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
      <Route path="/scanner/stop-hunter-pro"  element={<ProtectedRoute><ScannerPage /></ProtectedRoute>} />
      <Route path="/scanner/max-pain"         element={<ProtectedRoute><MaxPainScannerPage /></ProtectedRoute>} />
      <Route path="/pricing"          element={<ProtectedRoute><PricingPage /></ProtectedRoute>} />
      <Route path="/settings"         element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
      {/* Public auth flows */}
      <Route path="/forgot-password"   element={<ForgotPasswordPage />} />
      <Route path="/reset-password"    element={<ResetPasswordPage />} />
      {/* Public legal pages */}
      <Route path="/terms"             element={<TermsPage />} />
      <Route path="/privacy"           element={<PrivacyPage />} />
      <Route path="/risk-disclaimer"   element={<RiskDisclaimerPage />} />
      <Route path="/support"           element={<SupportPage />} />
      <Route path="*"                  element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}
