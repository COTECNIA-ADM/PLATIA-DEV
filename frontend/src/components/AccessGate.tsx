// Puerta de entrada común: recupera la sesión, pide el acceso si no la hay y avisa
// si la persona no tiene rol en esta aplicación.
import { lazy, Suspense, type ReactNode } from 'react'
import { Route, Routes } from 'react-router'
import { getAppCode } from '../lib/api'
import { APPS, type AppCode } from '../lib/apps'
import { useAuth } from '../lib/auth'
import BrandMark from './BrandMark'
import Login from '../pages/Login'
import { Empty, Spinner } from './ui'

const Health = lazy(() => import('../pages/Health'))

export function NotFound() {
  return <Empty title="Esta página no existe">Vuelve al inicio desde el menú.</Empty>
}

function NoAccess() {
  const { logout } = useAuth()
  const app = APPS[getAppCode() as AppCode]
  return (
    <div className="login">
      <div className="login-card">
        <div className="brand brand-large">
          <BrandMark />
          <span>PLATIA</span>
        </div>
        <p className="notice notice-warning">Tu usuario no tiene acceso a {app.name}.</p>
        <p className="muted">Si lo necesitas, pídeselo a un administrador. Mientras, puedes ir a otra aplicación:</p>
        <div className="btn-row">
          {Object.values(APPS)
            .filter((a) => a.code !== app.code)
            .map((a) => (
              <a key={a.code} className="btn" href={a.path}>
                {a.name}
              </a>
            ))}
        </div>
        <button className="btn btn-ghost" onClick={() => void logout()}>
          Entrar con otra cuenta
        </button>
      </div>
    </div>
  )
}

export default function AccessGate({ children }: { children: ReactNode }) {
  const { user, loading, denied } = useAuth()
  if (loading) return <Spinner label="Recuperando la sesión…" />
  if (denied) return <NoAccess />
  if (!user) {
    return (
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route path="status" element={<div className="content"><Health /></div>} />
          <Route path="*" element={<Login />} />
        </Routes>
      </Suspense>
    )
  }
  return <Suspense fallback={<Spinner />}>{children}</Suspense>
}
