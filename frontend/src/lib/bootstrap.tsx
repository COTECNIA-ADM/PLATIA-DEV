// Arranque común de las tres aplicaciones: caché de datos, router, avisos y sesión.
import { StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router'
import { ApiError, setAppCode } from './api'
import { APPS, type AppCode } from './apps'
import { AuthProvider } from './auth'
import { ToastProvider } from '../components/ui'
import '../styles.css'

export function mount(code: AppCode, app: ReactNode) {
  setAppCode(code)
  document.title = code === 'operations' ? 'PLATIA' : `PLATIA · ${APPS[code].name}`
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        // Un 4xx no se arregla reintentando (permiso, no existe, validación)
        retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      },
    },
  })
  const basename = APPS[code].path.replace(/\/$/, '') || '/'
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={basename}>
          <ToastProvider>
            <AuthProvider>{app}</AuthProvider>
          </ToastProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
}
