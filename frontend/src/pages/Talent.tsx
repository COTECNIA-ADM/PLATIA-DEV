import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { FAMILIES, SENIORITY, label } from '../lib/format'
import type { Page, ProfileSummary } from '../lib/types'
import { Badge, Empty, ErrorBox, Pager, Spinner, useDebounced } from '../components/ui'

export default function Talent() {
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const [skillText, setSkillText] = useState(params.get('skill') ?? '')
  const q = useDebounced(text.trim(), 300)
  const skill = useDebounced(skillText.trim(), 300)
  const filters = {
    q,
    skill,
    family: params.get('family') ?? '',
    seniority: params.get('seniority') ?? '',
    available: params.get('available') === 'true' ? 'true' : '',
    page: Number(params.get('page') ?? 1),
  }
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['talent', 'list', filters],
    queryFn: () => api<Page<ProfileSummary>>('/api/talent/profiles', { query: filters }),
    placeholderData: keepPreviousData,
  })
  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (!v) next.delete(k)
      else next.set(k, v)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next, { replace: true })
  }
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Talento</h1>
          <p className="muted">Perfiles del equipo para preparar propuestas y CV a medida.</p>
        </div>
      </header>
      <div className="toolbar">
        <input type="search" className="grow" placeholder="Nombre o titular" value={text} onChange={(e) => setText(e.target.value)} />
        <input type="search" placeholder="Competencia (p. ej. Kubernetes)" value={skillText} onChange={(e) => setSkillText(e.target.value)} />
        <select value={filters.family} onChange={(e) => update({ family: e.target.value })} aria-label="Familia">
          <option value="">Todas las familias</option>
          {Object.entries(FAMILIES).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select value={filters.seniority} onChange={(e) => update({ seniority: e.target.value })} aria-label="Nivel">
          <option value="">Todos los niveles</option>
          {Object.entries(SENIORITY).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <button className={`chip${filters.available ? ' chip-on' : ''}`} onClick={() => update({ available: filters.available ? null : 'true' })}>
          Disponibles
        </button>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay perfiles con estos filtros" />}
      <div className="cards-grid">
        {data?.items.map((p) => (
          <Link key={p.id} to={`/talent/${p.id}`} className="card profile-card">
            <div className="row-between">
              <strong>{p.full_name}</strong>
              {p.is_available ? <Badge tone="success">Disponible</Badge> : <Badge>Ocupado</Badge>}
            </div>
            {p.headline && <div className="muted">{p.headline}</div>}
            <div className="row-sub">
              {[label(FAMILIES, p.family), label(SENIORITY, p.seniority), p.years_experience ? `${p.years_experience} años` : null]
                .filter((x) => x && x !== '—')
                .join(' · ')}
            </div>
            <div className="tags">
              {p.skills.slice(0, 6).map((s) => (
                <Badge key={s}>{s}</Badge>
              ))}
            </div>
          </Link>
        ))}
      </div>
      {data && <Pager pagination={data.pagination} onPage={(p) => update({ page: String(p) })} />}
    </div>
  )
}
