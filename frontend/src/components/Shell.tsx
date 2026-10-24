// Estructura común de las tres aplicaciones: barra lateral con el menú, el cambio
// de aplicación y la cuenta; barra superior con lo que ponga cada app; y el contenido.
import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { getAppCode } from '../lib/api'
import { APPS, userApps } from '../lib/apps'
import { useAuth } from '../lib/auth'

export type NavItem = { to: string; label: string; icon: string; module?: string; ai?: string; end?: boolean }

export function initials(name: string | undefined) {
  return (name ?? '?')
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase()
}

/** Enlaces a las otras aplicaciones del usuario. Cambiar de app recarga la página:
 *  la sesión se recupera con la cookie y el rol se lee de nuevo para esa app. */
function AppSwitcher() {
  const { user } = useAuth()
  const current = getAppCode()
  const apps = userApps((user?.apps ?? []).map((a) => a.code))
  if (apps.length < 2) return null
  return (
    <div className="app-switcher" aria-label="Aplicaciones">
      {apps.map((a) =>
        a.code === current ? (
          <span key={a.code} className="app-link app-link-on" aria-current="true">
            {a.name}
          </span>
        ) : (
          <a key={a.code} className="app-link" href={a.path}>
            {a.name}
          </a>
        ),
      )}
    </div>
  )
}

export default function Shell({ nav, topbar }: { nav: NavItem[]; topbar?: ReactNode }) {
  const { user, can, hasAI, logout } = useAuth()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => setMenuOpen(false), [location.pathname])
  const items = nav.filter((n) => (!n.module || can(n.module, 'read')) && (!n.ai || hasAI(n.ai)))
  const code = getAppCode()

  return (
    <div className={`shell${menuOpen ? ' shell-menu-open' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">P</span>
          <span>
            PLATIA
            {code !== 'operations' && <small className="brand-app">{APPS[code as keyof typeof APPS]?.name}</small>}
          </span>
        </div>
        <nav>
          {items.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end ?? n.to === '/'} className="nav-link">
              <span className="nav-icon" aria-hidden>
                {n.icon}
              </span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <AppSwitcher />
          <NavLink to="/account" className="nav-link">
            <span className="avatar" aria-hidden>
              {initials(user?.full_name)}
            </span>
            <span className="sidebar-user">
              {user?.full_name}
              <small>Mi cuenta</small>
            </span>
          </NavLink>
          <button className="btn btn-ghost btn-small" onClick={() => void logout()}>
            Cerrar sesión
          </button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="btn-icon menu-toggle" onClick={() => setMenuOpen((o) => !o)} aria-label="Menú">
            ☰
          </button>
          {topbar ?? <div className="grow" />}
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
