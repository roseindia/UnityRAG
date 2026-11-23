import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from '@/app/App'
import { env } from '@/config/env'
import '@/styles/index.css'

async function boot() {
  // Mock adapter: development only, never bundled into the production path (import.meta.env.DEV is statically false).
  if (import.meta.env.DEV && env.mockApi) {
    const { installMockApi } = await import('@/services/mock/installMock')
    installMockApi()
  }
  createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
}
void boot()
