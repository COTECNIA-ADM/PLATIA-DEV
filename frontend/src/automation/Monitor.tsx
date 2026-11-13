// Monitorización del portal Low-Code (fase L4): salud por flujo e incidencias del flujo de errores.
import { useState, type FormEvent } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime, fmtRelative } from '../lib/format'
import type { Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Field, Modal, Pager, Spinner, errorMessage, useToast } from '../components/ui'
import type { Incident, WorkflowHealth } from './types'

const PERIODS: Record<string, string> = { '7': 'Últimos 7 días', '30': 'Últimos 30 días', '90': 'Últimos 90 días' }

function fmtSeconds(value: number | null): string {
  if (value === null) return '—'
  return value < 90 ? `${Math.round(value)} s` : `${Math.round(value / 60)} min`
}

function ResolveDialog({ incident, onClose }: { incident: Incident; onClose: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [note, setNote] = useState('')
  const resolve = useMutation({
    mutationFn: () =>
      api<Incident>(`/api/automation/incidents/${incident.id}/resolve`, {
        body: { version: incident.version, note: note.trim() || null },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['automation', 'incidents'] })
      void qc.invalidateQueries({ queryKey: ['automation', 'health'] })
      toast('Incidencia resuelta')
      onClose()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    resolve.mutate()
  }
  return (
    <Modal title="Resolver incidencia" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <p>
          {incident.workflow_name ?? incident.workflow_id}
          {incident.node && <span className="muted"> · paso «{incident.node}»</span>}
        </p>
        <Field label="Qué se ha hecho (opcional)">
          <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
        </Field>
        {resolve.error && <p className="notice notice-error">{errorMessage(resolve.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={resolve.isPending}>
            Marcar como resuelta
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function Monitor() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const days = PERIODS[params.get('days') ?? ''] ? params.get('days')! : '30'
  const status = params.get('status') ?? 'open'
  const workflowId = params.get('workflow_id') ?? ''
  const page = Number(params.get('page') ?? 1)
  const [resolving, setResolving] = useState<Incident | null>(null)

  const health = useQuery({
    queryKey: ['automation', 'health', days],
    queryFn: () => api<{ days: number; items: WorkflowHealth[]; open_incidents: number }>('/api/automation/health', { query: { days } }),
  })
  const list = useQuery({
    queryKey: ['automation', 'incidents', status, workflowId, page],
    queryFn: () =>
      api<Page<Incident>>('/api/automation/incidents', {
        query: { status: status === 'all' ? '' : status, workflow_id: workflowId, page },
      }),
    placeholderData: keepPreviousData,
  })

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    setParams(next, { replace: true })
  }

  const filteredName = health.data?.items.find((w) => w.workflow_id === workflowId)?.workflow_name ?? workflowId

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Monitorización</h1>
          <p className="muted">Cómo van las automatizaciones y qué ha fallado. Los fallos llegan desde el flujo de errores de n8n.</p>
        </div>
      </header>

      <section className="card">
        <header className="card-head">
          <h2>Salud por automatización</h2>
          <select value={days} onChange={(e) => setFilter('days', e.target.value)} aria-label="Periodo">
            {Object.entries(PERIODS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </header>
        {health.isLoading && <Spinner />}
        {health.error && <ErrorBox error={health.error} onRetry={() => void health.refetch()} />}
        {health.data && !health.data.items.length && <p className="muted">No hay ejecuciones ni incidencias en este periodo.</p>}
        {health.data && health.data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table" aria-label="Salud por automatización">
              <thead>
                <tr>
                  <th>Automatización</th>
                  <th>Ejecuciones</th>
                  <th>Éxito</th>
                  <th>Fallidas</th>
                  <th>En marcha</th>
                  <th>Duración media</th>
                  <th>Última</th>
                  <th>Incidencias abiertas</th>
                </tr>
              </thead>
              <tbody>
                {health.data.items.map((w) => (
                  <tr key={w.workflow_id}>
                    <td className="row-title">{w.workflow_name ?? w.workflow_id}</td>
                    <td>{w.runs}</td>
                    <td>{w.success_rate === null ? '—' : `${w.success_rate} %`}</td>
                    <td>{w.failed}</td>
                    <td>{w.open}</td>
                    <td>{fmtSeconds(w.avg_seconds)}</td>
                    <td>{w.last_run_at ? fmtRelative(w.last_run_at) : '—'}</td>
                    <td>
                      {w.open_incidents > 0 ? (
                        <button className="btn btn-small" onClick={() => setFilter('workflow_id', w.workflow_id)}>
                          <Badge tone="danger">{w.open_incidents}</Badge> Ver
                        </button>
                      ) : (
                        '0'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card">
        <header className="card-head">
          <h2>Incidencias</h2>
          <div className="toolbar">
            <select value={status} onChange={(e) => setFilter('status', e.target.value)} aria-label="Estado de la incidencia">
              <option value="open">Abiertas</option>
              <option value="resolved">Resueltas</option>
              <option value="all">Todas</option>
            </select>
            {workflowId && (
              <button className="btn btn-small btn-ghost" onClick={() => setFilter('workflow_id', '')}>
                Quitar filtro: {filteredName} ✕
              </button>
            )}
          </div>
        </header>
        {list.isLoading && <Spinner />}
        {list.error && <ErrorBox error={list.error} onRetry={() => void list.refetch()} />}
        {list.data && !list.data.items.length && (
          <Empty title={status === 'open' ? 'No hay incidencias abiertas' : 'No hay incidencias'} />
        )}
        {list.data && list.data.items.length > 0 && (
          <ul className="plain-list">
            {list.data.items.map((i) => (
              <li key={i.id} className="row-between">
                <span>
                  <strong>{i.workflow_name ?? i.workflow_id}</strong>{' '}
                  <Badge tone={i.status === 'open' ? 'danger' : 'neutral'}>{i.status === 'open' ? 'Abierta' : 'Resuelta'}</Badge>
                  <div className="row-sub">
                    {fmtDateTime(i.created_at)}
                    {i.node && <> · paso «{i.node}»</>}
                    {i.execution_id && <> · ejecución de n8n {i.execution_id}</>}
                    {i.run_id && (
                      <>
                        {' · '}
                        <Link to={`/runs/${i.run_id}`}>ejecución de PLATIA</Link>
                      </>
                    )}
                  </div>
                  {i.message && <div className="text-block muted">{i.message}</div>}
                  {i.resolution_note && <div className="text-block">Resolución: {i.resolution_note}</div>}
                </span>
                {i.status === 'open' && can('automations', 'manage') && (
                  <button className="btn btn-small" onClick={() => setResolving(i)}>
                    Resolver
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
        {list.data && <Pager pagination={list.data.pagination} onPage={(p) => setFilter('page', String(p))} />}
      </section>
      {resolving && <ResolveDialog incident={resolving} onClose={() => setResolving(null)} />}
    </div>
  )
}
