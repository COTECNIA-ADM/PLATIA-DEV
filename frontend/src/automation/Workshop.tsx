// Taller del portal Low-Code: fichas del catálogo en preparación, revisión o publicadas.
import { useState, type FormEvent } from 'react'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { api } from '../lib/api'
import { fmtRelative } from '../lib/format'
import type { Page } from '../lib/types'
import { Empty, ErrorBox, Field, Modal, Pager, Spinner, errorMessage } from '../components/ui'
import { CATEGORY, ENTRY_STATUS, EntryStatusBadge, SourceNotice } from './common'
import type { Candidate, Category, Entry, EntryStatus, Source } from './types'

function NewEntry({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const { data, error, isLoading } = useQuery({
    queryKey: ['automation', 'workflows'],
    queryFn: () => api<{ items: Candidate[]; source: Source }>('/api/automation/workflows'),
  })
  const free = (data?.items ?? []).filter((w) => w.entry_id === null)
  const [form, setForm] = useState({ workflow_id: '', title: '', description: '', category: 'ciclo_comercial' })
  const create = useMutation({
    mutationFn: () =>
      api<Entry>('/api/automation/entries', { body: { ...form, description: form.description || null, fields: [] } }),
    onSuccess: (entry) => navigate(`/workshop/${entry.id}`),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    create.mutate()
  }

  return (
    <Modal title="Nueva ficha" onClose={onClose}>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} />}
      {data && <SourceNotice source={data.source} />}
      {data && (
        <form className="stack" onSubmit={submit}>
          <Field label="Flujo de n8n" hint="Solo salen los flujos con la etiqueta del catálogo que aún no tienen ficha.">
            <select
              required
              value={form.workflow_id}
              onChange={(e) => {
                const w = free.find((x) => x.id === e.target.value)
                setForm({ ...form, workflow_id: e.target.value, title: form.title || w?.name || '' })
              }}
            >
              <option value="">Elige un flujo…</option>
              {free.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Título">
            <input required minLength={3} maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Descripción" hint="Qué hace y cuándo usarla, en una o dos frases.">
            <textarea rows={3} maxLength={2000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Field label="Área">
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {(Object.keys(CATEGORY) as Category[]).map((c) => (
                <option key={c} value={c}>
                  {CATEGORY[c]}
                </option>
              ))}
            </select>
          </Field>
          {create.error && (
            <p className="notice notice-error" role="alert">
              {errorMessage(create.error)}
            </p>
          )}
          <div className="actions">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancelar
            </button>
            <button type="submit" className="btn btn-primary" disabled={create.isPending}>
              Crear ficha
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}

export default function Workshop() {
  const [params, setParams] = useSearchParams()
  const [creating, setCreating] = useState(false)
  const status = params.get('status') ?? ''
  const page = Number(params.get('page') ?? 1)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['automation', 'entries', status, page],
    queryFn: () => api<Page<Entry>>('/api/automation/entries', { query: { status, page } }),
    placeholderData: keepPreviousData,
  })

  function setFilter(value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set('status', value)
    else next.delete('status')
    next.delete('page')
    setParams(next, { replace: true })
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Taller</h1>
          <p className="muted">
            Prepara la ficha de cada flujo de n8n, pasa las comprobaciones y envíala a revisión. Quien administra la
            publica en el catálogo.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setCreating(true)}>
          Nueva ficha
        </button>
      </header>
      <div className="toolbar">
        <select value={status} onChange={(e) => setFilter(e.target.value)} aria-label="Estado">
          <option value="">Todos los estados</option>
          {(Object.keys(ENTRY_STATUS) as EntryStatus[]).map((s) => (
            <option key={s} value={s}>
              {ENTRY_STATUS[s].label}
            </option>
          ))}
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay fichas" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Ficha</th>
                <th>Área</th>
                <th>Estado</th>
                <th>Creada</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((e) => (
                <tr key={e.id}>
                  <td className="row-title">
                    <Link to={`/workshop/${e.id}`}>{e.title}</Link>
                  </td>
                  <td>{CATEGORY[e.category] ?? e.category}</td>
                  <td>
                    <EntryStatusBadge status={e.status} />
                  </td>
                  <td>{fmtRelative(e.created_at)}</td>
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
      {creating && <NewEntry onClose={() => setCreating(false)} />}
    </div>
  )
}
