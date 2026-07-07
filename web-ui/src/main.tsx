import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import 'katex/dist/katex.min.css'
import App from './App.tsx'
import AnalyticsRouteTracker from './components/AnalyticsRouteTracker'
import { AuthProvider } from './contexts/AuthContext'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <AnalyticsRouteTracker />
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
