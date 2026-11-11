// Catálogo del portal Low-Code: las automatizaciones publicadas y el botón para lanzarlas.
import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Badge, Empty, ErrorBox, Pager, Spinner, useDebounced } from '../components/ui'
import { CATEGORY, SourceNotice } from './common'
import Launch from './Launch'
import type { CatalogItem, CatalogPage, Category } from './types'

export default function Catalog() {
  const { can } = useAuth()
  const canRun = can('automations', 'run')
  const [launching, setLaunching] = useState<CatalogItem | null>(null)
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const q = useDebounced(text.trim(), 300)
  const category = params.get('category') ?? ''
  const active = params.get('active') ?? ''
  const page = Number(params.get('page') ?? 1)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['automation', 'catalog', q, category, active, page],
    queryFn: () => api<CatalogPage>('/api/automation/catalog', { query: { q, category, active, page } }),
    placeholderData: keepPreviousData,
  })

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    setParams(next, { replace: true })
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Catálogo</h1>
          <p className="muted">Automatizaciones revisadas y publicadas para PLATIA.</p>
        </div>
      </header>
      <div className="toolbar">
        <input
          type="search"
          className="grow"
          placeholder="Buscar por nombre o descripción"
          aria-label="Buscar"
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setFilter('q', e.target.value.trim())
          }}
        />
        <select value={category} onChange={(e) => setFilter('category', e.target.value)} aria-label="Área">
          <option value="">Todas las áreas</option>
          {(Object.keys(CATEGORY) as Category[]).map((c) => (
            <option key={c} value={c}>
              {CATEGORY[c]}
            </option>
          ))}
        </select>
        <select value={active} onChange={(e) => setFilter('active', e.target.value)} aria-label="Estado">
          <option value="">Todas</option>
          <option value="true">Activas</option>
          <option value="false">En pausa</option>
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && <SourceNotice source={data.source} />}
      {data && !data.items.length && <Empty title="No hay automatizaciones publicadas" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Automatización</th>
                <th>Área</th>
                <th>Estado</th>
                {canRun && <th aria-label="Acciones" />}
              </tr>
            </thead>
            <tbody>
              {data.items.map((w) => (
                <tr key={w.id}>
                  <td>
                    <div className="row-title">{w.title}</div>
                    {w.description && <div className="muted">{w.description}</div>}
                  </td>
                  <td>{CATEGORY[w.category] ?? w.category}</td>
                  <td>
                    <Badge tone={w.active ? 'success' : 'neutral'}>{w.active ? 'Activa' : 'En pausa'}</Badge>
                  </td>
                  {canRun && (
                    <td>
                      {w.launchable ? (
                        <button className="btn btn-primary btn-small" onClick={() => setLaunching(w)}>
                          Lanzar
                        </button>
                      ) : (
                        <span className="muted" title="El flujo está en pausa o n8n no responde">
                          No disponible
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && (
        <Pager
          pagination={data.pagination}
          onPage={(p) => {
            const next = new URLSearchParams(params)
            next.set('page', String(p))
            setParams(next)
          }}
        />
      )}
      {launching && <Launch item={launching} onClose={() => setLaunching(null)} />}
    </div>
  )
}
