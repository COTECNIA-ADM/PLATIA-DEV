// Estructura de la aplicación de operaciones: el armazón común (Shell) con el buscador
// global y la campana de avisos en la barra superior.
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { NavLink, useNavigate } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { QuickSearch } from '../lib/types'
import { Highlight } from './text'
import Shell, { type NavItem } from './Shell'
import { useDebounced } from './ui'


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
  return (
    <Shell
      nav={NAV}
      topbar={
        <>
          <QuickSearchBox />
          <Bell />
        </>
      }
    />
  )
}
