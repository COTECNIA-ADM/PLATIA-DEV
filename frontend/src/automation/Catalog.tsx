// Catálogo del portal Low-Code: los flujos de n8n publicados para PLATIA (solo lectura).
import { useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { api } from '../lib/api'
import { fmtRelative } from '../lib/format'
import { Badge, Empty, ErrorBox, Pager, Spinner, useDebounced } from '../components/ui'
import { SourceNotice } from './common'
import type { CatalogPage } from './types'

export default function Catalog() {
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const q = useDebounced(text.trim(), 300)
  const active = params.get('active') ?? ''
  const page = Number(params.get('page') ?? 1)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['automation', 'catalog', q, active, page],
    queryFn: () => api<CatalogPage>('/api/automation/catalog', { query: { q, active, page } }),
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
          <p className="muted">Automatizaciones publicadas para PLATIA. Solo aparecen las revisadas.</p>
        </div>
      </header>
      <div className="toolbar">
        <input
          type="search"
          className="grow"
          placeholder="Buscar por nombre o etiqueta"
          aria-label="Buscar"
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setFilter('q', e.target.value.trim())
          }}
        />
        <select value={active} onChange={(e) => setFilter('active', e.target.value)} aria-label="Estado">
          <option value="">Todas</option>
          <option value="true">Activas</option>
          <option value="false">En pausa</option>
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && <SourceNotice source={data.source} />}
      {data && !data.items.length && data.source.reachable && <Empty title="No hay automatizaciones publicadas" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Automatización</th>
                <th>Estado</th>
                <th>Etiquetas</th>
                <th>Actualizada</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((w) => (
                <tr key={w.id}>
                  <td className="row-title">{w.name}</td>
                  <td>
                    <Badge tone={w.active ? 'success' : 'neutral'}>{w.active ? 'Activa' : 'En pausa'}</Badge>
                  </td>
                  <td>{w.tags.join(', ') || '—'}</td>
                  <td>{fmtRelative(w.updated_at)}</td>
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
    </div>
  )
}
