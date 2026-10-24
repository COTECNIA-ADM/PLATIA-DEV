// Inicio: lo que pide atención hoy (Capítulo 16: la pantalla que se abre cada mañana).
import { useState } from 'react'
import { Link } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { daysUntil, fmtDate, fmtMoney, fmtRelative } from '../lib/format'
import type { Alert, Notification, OpportunitySearch, Page, ProposalSummary } from '../lib/types'
import { OpportunityStatus, ProposalStatus } from '../components/status'
import { Empty, ScoreBar, Spinner, Stat } from '../components/ui'
import { NewOpportunity } from './Opportunities'

function greeting() {
  const h = new Date().getHours()
  return h < 14 ? 'Buenos días' : h < 21 ? 'Buenas tardes' : 'Buenas noches'
}

export default function Home() {
  const { user, can, hasAI } = useAuth()
  const [creating, setCreating] = useState(false)
  const canOpp = can('opportunities', 'read')
  const canProp = can('proposals', 'read')

  const closing = useQuery({
    queryKey: ['opportunities', 'search', 'home-closing'],
    queryFn: () =>
      api<OpportunitySearch>('/api/search/opportunities', {
        body: { only_open: true, deadline_within_days: 14, sort: 'deadline', per_page: 6, facets: false },
      }),
    enabled: canOpp,
  })
  const mine = useQuery({
    queryKey: ['opportunities', 'search', 'home-mine'],
    queryFn: () =>
      api<OpportunitySearch>('/api/search/opportunities', { body: { only_open: true, owner: 'me', per_page: 1, facets: true } }),
    enabled: canOpp,
  })
  const best = useQuery({
    queryKey: ['opportunities', 'search', 'home-best'],
    queryFn: () =>
      api<OpportunitySearch>('/api/search/opportunities', {
        body: { only_open: true, phase: ['F1'], sort: '-relevance_score', per_page: 5, facets: false },
      }),
    enabled: canOpp,
  })
  const toReview = useQuery({
    queryKey: ['proposals', 'list', 'home-review'],
    queryFn: () => api<Page<ProposalSummary>>('/api/proposals', { query: { to_review: 'true', per_page: 5 } }),
    enabled: canProp && can('proposals', 'approve'),
  })
  const drafts = useQuery({
    queryKey: ['proposals', 'list', 'home-drafts'],
    queryFn: () => api<Page<ProposalSummary>>('/api/proposals', { query: { mine: 'true', status: 'draft,in_review', per_page: 5 } }),
    enabled: canProp,
  })
  const notifications = useQuery({
    queryKey: ['notifications', 'home'],
    queryFn: () => api<Page<Notification>>('/api/notifications', { query: { unread: 'true', per_page: 5 } }),
    enabled: can('notifications', 'read'),
  })
  const alerts = useQuery({
    queryKey: ['alerts', 'home'],
    queryFn: () => api<Page<Alert>>('/api/alerts', { query: { open: 'true', per_page: 5 } }),
    enabled: can('alerts', 'read'),
  })

  const phases = mine.data?.facets?.phase ?? {}

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>
            {greeting()}, {user?.full_name.split(' ')[0]}
          </h1>
          <p className="muted">Esto es lo que pide tu atención.</p>
        </div>
        <div className="btn-row">
          {can('opportunities', 'write') && (
            <button className="btn" onClick={() => setCreating(true)}>
              Nueva oportunidad
            </button>
          )}
          {can('documents', 'upload') && (
            <Link className="btn" to="/documents">
              Subir documento
            </Link>
          )}
          {hasAI('copilot_chat') && can('copilot', 'write') && (
            <Link className="btn btn-primary" to="/copilot">
              Preguntar al copiloto
            </Link>
          )}
        </div>
      </header>

      {canOpp && (
        <div className="stats">
          <Stat label="Mis oportunidades abiertas" value={mine.data?.pagination.total ?? '…'} hint={<Link to="/opportunities?mine=true">Ver</Link>} />
          <Stat label="Cierran en 14 días" value={closing.data?.pagination.total ?? '…'} hint={<Link to="/opportunities?closing=30&sort=deadline">Ver</Link>} />
          <Stat label="En propuesta (F4)" value={phases.F4 ?? 0} />
          {can('proposals', 'approve') && (
            <Stat label="Propuestas por revisar" value={toReview.data?.pagination.total ?? '…'} hint={<Link to="/proposals?review=true">Ver</Link>} />
          )}
        </div>
      )}

      <div className="home-grid">
        {canOpp && (
          <section className="card">
            <h2>Cierran pronto</h2>
            {closing.isLoading && <Spinner />}
            {closing.data && !closing.data.items.length && <p className="muted">Nada cierra en las próximas dos semanas.</p>}
            <ul className="plain-list">
              {closing.data?.items.map((o) => {
                const d = daysUntil(o.deadline)
                return (
                  <li key={o.id} className="row-between">
                    <span>
                      <Link to={`/opportunities/${o.id}`}>{o.title}</Link>
                      <div className="row-sub">
                        <OpportunityStatus status={o.status} /> {fmtMoney(o.estimated_value_eur)}
                      </div>
                    </span>
                    <span className={d !== null && d <= 3 ? 'text-danger' : 'text-warning'}>
                      {d === 0 ? 'hoy' : `${d} días`}
                      <div className="row-sub">{fmtDate(o.deadline)}</div>
                    </span>
                  </li>
                )
              })}
            </ul>
          </section>
        )}

        {canOpp && (
          <section className="card">
            <h2>Nuevas más relevantes</h2>
            {best.isLoading && <Spinner />}
            {best.data && !best.data.items.length && <p className="muted">No hay oportunidades nuevas sin revisar.</p>}
            <ul className="plain-list">
              {best.data?.items.map((o) => (
                <li key={o.id} className="row-between">
                  <Link to={`/opportunities/${o.id}`}>{o.title}</Link>
                  <ScoreBar value={o.relevance_score} />
                </li>
              ))}
            </ul>
          </section>
        )}

        {canProp && (
          <section className="card">
            <h2>Mis propuestas en curso</h2>
            {drafts.data && !drafts.data.items.length && <p className="muted">No tienes propuestas en borrador ni en revisión.</p>}
            <ul className="plain-list">
              {drafts.data?.items.map((p) => (
                <li key={p.id} className="row-between">
                  <Link to={`/proposals/${p.id}`}>{p.title}</Link>
                  <ProposalStatus status={p.status} />
                </li>
              ))}
            </ul>
            {!!toReview.data?.items.length && (
              <>
                <h3>Esperan tu revisión</h3>
                <ul className="plain-list">
                  {toReview.data.items.map((p) => (
                    <li key={p.id}>
                      <Link to={`/proposals/${p.id}`}>{p.title}</Link>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
        )}

        <section className="card">
          <header className="card-head">
            <h2>Avisos</h2>
            <Link to="/notifications">Ver todos</Link>
          </header>
          {!!alerts.data?.items.length && (
            <ul className="plain-list">
              {alerts.data.items.map((a) => (
                <li key={a.id} className="notice notice-warning">
                  {a.opportunity_id ? <Link to={`/opportunities/${a.opportunity_id}`}>{a.message}</Link> : a.message}
                </li>
              ))}
            </ul>
          )}
          {notifications.data && !notifications.data.items.length && !alerts.data?.items.length && (
            <Empty title="Estás al día">No tienes avisos sin leer.</Empty>
          )}
          <ul className="plain-list">
            {notifications.data?.items.map((n) => (
              <li key={n.id}>
                {n.link ? <Link to={n.link}>{n.title}</Link> : <strong>{n.title}</strong>}
                <div className="row-sub">
                  {n.body} · {fmtRelative(n.created_at)}
                </div>
              </li>
            ))}
          </ul>
        </section>
      </div>
      {creating && <NewOpportunity onClose={() => setCreating(false)} />}
    </div>
  )
}
