// Estructura de la aplicación: barra lateral, barra superior con el buscador global y
// la campana de avisos, y el contenido de cada página.
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { QuickSearch } from '../lib/types'
import { Highlight } from './text'
import { useDebounced } from './ui'

type NavItem = { to: string; label: string; icon: string; module?: string; ai?: string }

const NAV: NavItem[] = [
  { to: '/', label: 'Inicio', icon: '⌂' },
  { to: '/opportunities', label: 'Oportunidades', icon: '◎', module: 'opportunities' },
  { to: '/documents', label: 'Documentos', icon: '▤', module: 'documents' },
  { to: '/proposals', label: 'Propuestas', icon: '✎', module: 'proposals' },
  { to: '/copilot', label: 'Copiloto', icon: '✦', module: 'copilot', ai: 'copilot_chat' },
  { to: '/clients', label: 'Clientes', icon: '◇', module: 'clients' },
  { to: '/talent', label: 'Talento', icon: '☺', module: 'talent' },
]

const GROUP_LABEL: Record<string, string> = {
  opportunities: 'Oportunidades',
  documents: 'Documentos',
  clients: 'Clientes',
}

function QuickSearchBox() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const q = useDebounced(text.trim(), 250)
  const boxRef = useRef<HTMLFormElement>(null)
  const { data } = useQuery({
    queryKey: ['quick-search', q],
    queryFn: () => api<QuickSearch>('/api/search', { query: { q, limit: 5 } }),
    enabled: q.length >= 2,
    staleTime: 30_000,
  })

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!boxRef.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!text.trim()) return
    setOpen(false)
    navigate(`/search?q=${encodeURIComponent(text.trim())}`)
  }

  function go(path: string) {
    setOpen(false)
    setText('')
    navigate(path)
  }

  const groups = (data?.groups ?? []).filter((g) => g.items.length)
  return (
    <form className="quicksearch" onSubmit={submit} ref={boxRef} role="search">
      <input
        type="search"
        placeholder="Busca o pregunta: «licitaciones de ciberseguridad que cierran este mes»"
        value={text}
        maxLength={500}
        onChange={(e) => {
          setText(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
        aria-label="Buscar en la plataforma"
      />
      {open && q.length >= 2 && (
        <div className="quicksearch-panel">
          {groups.map((g) => (
            <div key={g.type}>
              <div className="quicksearch-group">
                {GROUP_LABEL[g.type]} <span className="muted">{g.total}</span>
              </div>
              {g.items.map((item) => (
                <button key={item.id} type="button" className="quicksearch-item" onClick={() => go(`/${g.type}/${item.id}`)}>
                  <span>
                    <Highlight html={item.highlight} fallback={item.title} />
                  </span>
                  {item.subtitle && <small className="muted">{item.subtitle}</small>}
                </button>
              ))}
            </div>
          ))}
          <button type="submit" className="quicksearch-item quicksearch-ask">
            Pulsa Intro para que el asistente interprete «{text.trim()}»
          </button>
        </div>
      )}
    </form>
  )
}

function Bell() {
  const { can } = useAuth()
  const { data } = useQuery({
    queryKey: ['unread-count'],
    queryFn: () => api<{ unread: number }>('/api/notifications/unread-count'),
    refetchInterval: 60_000,
    enabled: can('notifications', 'read'),
  })
  const unread = data?.unread ?? 0
  return (
    <NavLink to="/notifications" className="bell" aria-label={`Avisos: ${unread} sin leer`}>
      <span aria-hidden>🔔</span>
      {unread > 0 && <span className="bell-count">{unread > 99 ? '99+' : unread}</span>}
    </NavLink>
  )
}

export default function Layout() {
  const { user, can, hasAI, logout } = useAuth()
  const location = useLocation()
  const [menuOpen, setMenuOpen] = useState(false)
  useEffect(() => setMenuOpen(false), [location.pathname])

  const items = NAV.filter((n) => (!n.module || can(n.module, 'read')) && (!n.ai || hasAI(n.ai)))
  const initials = (user?.full_name ?? '?')
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase()

  return (
    <div className={`shell${menuOpen ? ' shell-menu-open' : ''}`}>
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">P</span>
          <span>PLATIA</span>
        </div>
        <nav>
          {items.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'} className="nav-link">
              <span className="nav-icon" aria-hidden>
                {n.icon}
              </span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <NavLink to="/account" className="nav-link">
            <span className="avatar" aria-hidden>
              {initials}
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
          <QuickSearchBox />
          <Bell />
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
