import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import 'katex/dist/katex.min.css'
import App from './App.tsx'
import AnalyticsRouteTracker from './components/AnalyticsRouteTracker'
import { AuthProvider } from './contexts/AuthContext'
import { prepareBlogBootstrap } from './utils/blogBootstrap'
import { getLoadedBlogPage, preloadBlogPage } from './utils/blogPageLoader'

async function start() {
  const preparation = await prepareBlogBootstrap(document, window.location.pathname, preloadBlogPage)
  if (preparation === 'preserve-ssr') return
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <BrowserRouter>
        <AuthProvider>
          <AnalyticsRouteTracker />
          <App initialBlogPage={getLoadedBlogPage() ?? undefined} />
        </AuthProvider>
      </BrowserRouter>
    </StrictMode>,
  )
}

void start()
