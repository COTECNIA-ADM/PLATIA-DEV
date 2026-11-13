// Solicitudes que llegan del formulario web a través de n8n (caso P2, ADR-020).
import { Link, useSearchParams } from 'react-router'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtRelative } from '../lib/format'
import type { LeadStatus, LeadSummary, Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Pager, Spinner, type Tone } from '../components/ui'

export const LEAD_STATUS: Record<LeadStatus, [string, Tone]> = {
  new: ['Pendiente', 'warning'],
  converted: ['Convertida', 'success'],
  discarded: ['Descartada', 'neutral'],
}

export const RESOLUTION: Record<string, string> = { contact: 'en contacto', opportunity: 'en oportunidad' }

export function LeadStatusBadge({ lead }: { lead: Pick<LeadSummary, 'status' | 'resolution'> }) {
  const [label, tone] = LEAD_STATUS[lead.status]
  return (
    <Badge tone={tone}>
      {label}
      {lead.resolution ? ` ${RESOLUTION[lead.resolution]}` : ''}
    </Badge>
  )
}

export default function Leads() {
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? 'new'
  const page = Number(params.get('page') ?? 1)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['leads', 'list', status, page],
    queryFn: () => api<Page<LeadSummary>>('/api/leads', { query: { status: status === 'all' ? '' : status, page } }),
    placeholderData: keepPreviousData,
  })

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Solicitudes</h1>
          <p className="muted">
            Lo que llega del formulario web. Nada se da de alta solo: decides tú si es un contacto, una oportunidad o se
            descarta.
          </p>
        </div>
      </header>
      <div className="toolbar">
        <select value={status} onChange={(e) => setParams({ status: e.target.value })} aria-label="Estado">
          <option value="new">Pendientes</option>
          <option value="converted">Convertidas</option>
          <option value="discarded">Descartadas</option>
          <option value="all">Todas</option>
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title={status === 'new' ? 'No hay solicitudes pendientes' : 'No hay solicitudes'} />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Quién</th>
                <th>Empresa</th>
                <th>Asunto</th>
                <th>Estado</th>
                <th>Recibida</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((l) => (
                <tr key={l.id}>
                  <td>
                    <Link to={`/leads/${l.id}`} className="row-title">
                      {l.full_name}
                    </Link>
                    <div className="row-sub">{l.email}</div>
                  </td>
                  <td>{l.company ?? '—'}</td>
                  <td>{l.subject ?? '—'}</td>
                  <td>
                    <LeadStatusBadge lead={l} />
                  </td>
                  <td>{fmtRelative(l.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager pagination={data.pagination} onPage={(p) => setParams({ status, page: String(p) })} />}
    </div>
  )
}
