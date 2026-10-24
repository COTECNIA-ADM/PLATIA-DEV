import { Link, useSearchParams } from 'react-router'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { PROPOSAL_STATUS, PROPOSAL_TYPES, fmtMoney, fmtRelative, label } from '../lib/format'
import type { Page, ProposalSummary } from '../lib/types'
import { GenerationStatus, ProposalStatus } from '../components/status'
import { Empty, ErrorBox, Pager, Spinner } from '../components/ui'

export default function Proposals() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const filters = {
    status: params.get('status') ?? '',
    proposal_type: params.get('type') ?? '',
    mine: params.get('mine') === 'true' ? 'true' : '',
    to_review: params.get('review') === 'true' ? 'true' : '',
    page: Number(params.get('page') ?? 1),
  }
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['proposals', 'list', filters],
    queryFn: () => api<Page<ProposalSummary>>('/api/proposals', { query: filters }),
    placeholderData: keepPreviousData,
    refetchInterval: (q) =>
      q.state.data?.items.some((p) => p.generation_status === 'queued' || p.generation_status === 'running') ? 5000 : false,
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
          <h1>Propuestas</h1>
          <p className="muted">Para crear una, abre la oportunidad y pulsa «Nueva propuesta».</p>
        </div>
      </header>
      <div className="toolbar">
        <select value={filters.status} onChange={(e) => update({ status: e.target.value })} aria-label="Estado">
          <option value="">Todos los estados</option>
          {Object.entries(PROPOSAL_STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select value={filters.proposal_type} onChange={(e) => update({ type: e.target.value })} aria-label="Tipo">
          <option value="">Todos los tipos</option>
          {Object.entries(PROPOSAL_TYPES).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <button className={`chip${filters.mine ? ' chip-on' : ''}`} onClick={() => update({ mine: filters.mine ? null : 'true' })}>
          Mías
        </button>
        {can('proposals', 'approve') && (
          <button className={`chip${filters.to_review ? ' chip-on' : ''}`} onClick={() => update({ review: filters.to_review ? null : 'true' })}>
            Pendientes de revisar
          </button>
        )}
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay propuestas con estos filtros" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Propuesta</th>
                <th>Tipo</th>
                <th>Estado</th>
                <th>Redacción IA</th>
                <th className="num">Importe</th>
                <th>Actualizada</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((p) => (
                <tr key={p.id}>
                  <td>
                    <Link to={`/proposals/${p.id}`} className="row-title">
                      {p.title}
                    </Link>
                    <div className="row-sub">
                      <Link to={`/opportunities/${p.opportunity_id}`}>{p.opportunity_title}</Link> · v{p.version_number}
                    </div>
                  </td>
                  <td>{label(PROPOSAL_TYPES, p.proposal_type)}</td>
                  <td>
                    <ProposalStatus status={p.status} />
                  </td>
                  <td>
                    <GenerationStatus status={p.generation_status} />
                  </td>
                  <td className="num">{fmtMoney(p.total_amount_eur)}</td>
                  <td>{fmtRelative(p.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager pagination={data.pagination} onPage={(p) => update({ page: String(p) })} />}
    </div>
  )
}
