// Ficha del taller: datos que ve la persona, campos del formulario, comprobaciones y revisión.
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime } from '../lib/format'
import { Badge, ErrorBox, Field, Spinner, errorMessage } from '../components/ui'
import { CATEGORY, EntryStatusBadge, FIELD_TYPE } from './common'
import type { Category, Entry, FieldDef, FieldType } from './types'

type Row = { name: string; label: string; type: FieldType; required: boolean; options: string }

const toRows = (fields: FieldDef[]): Row[] =>
  fields.map((f) => ({ name: f.name, label: f.label, type: f.type, required: !!f.required, options: (f.options ?? []).join(', ') }))

const toFields = (rows: Row[]): FieldDef[] =>
  rows
    .filter((r) => r.name.trim())
    .map((r) => ({
      name: r.name.trim(),
      label: r.label.trim() || r.name.trim(),
      type: r.type,
      required: r.required,
      options: r.type === 'select' ? r.options.split(',').map((o) => o.trim()).filter(Boolean) : [],
    }))

function Checks({ entry }: { entry: Entry }) {
  if (!entry.checked_at) return <p className="muted">Todavía no se ha comprobado el flujo.</p>
  if (!entry.checks.length)
    return (
      <p className="notice notice-info" role="status">
        El flujo pasa todas las comprobaciones.
      </p>
    )
  return (
    <ul className="stack" aria-label="Resultado de las comprobaciones">
      {entry.checks.map((c, i) => (
        <li key={i}>
          <Badge tone={c.level === 'error' ? 'danger' : 'warning'}>{c.level === 'error' ? 'Error' : 'Aviso'}</Badge>{' '}
          {c.message}
          {c.node && <span className="muted"> · nodo «{c.node}»</span>}
        </li>
      ))}
    </ul>
  )
}

export default function EntryDetail() {
  const { id } = useParams()
  const { can } = useAuth()
  const qc = useQueryClient()
  const key = ['automation', 'entry', id]
  const { data: entry, error, isLoading, refetch } = useQuery({
    queryKey: key,
    queryFn: () => api<Entry>(`/api/automation/entries/${id}`),
  })
  const [form, setForm] = useState({ title: '', description: '', category: 'ciclo_comercial' as Category })
  const [rows, setRows] = useState<Row[]>([])
  const [note, setNote] = useState('')
  useEffect(() => {
    if (!entry) return
    setForm({ title: entry.title, description: entry.description ?? '', category: entry.category })
    setRows(toRows(entry.fields))
  }, [entry])

  const done = (next: Entry) => qc.setQueryData(key, { ...next, input_names: entry?.input_names })
  const save = useMutation({
    mutationFn: () =>
      api<Entry>(`/api/automation/entries/${id}`, {
        method: 'PATCH',
        body: { ...form, description: form.description || null, fields: toFields(rows), version: entry!.version },
      }),
    onSuccess: done,
  })
  const action = useMutation({
    mutationFn: (step: { path: string; body?: Record<string, unknown> }) =>
      api<Entry>(`/api/automation/entries/${id}/${step.path}`, { body: { version: entry!.version, ...step.body } }),
    onSuccess: done,
    onSettled: () => void qc.invalidateQueries({ queryKey: key }),
  })
  const check = useMutation({
    mutationFn: () => api<Entry>(`/api/automation/entries/${id}/check`, { body: {} }),
    onSuccess: done,
  })

  if (isLoading) return <Spinner />
  if (error || !entry) return <ErrorBox error={error} onRetry={() => void refetch()} />
  const editable = entry.status === 'draft' || entry.status === 'retired'
  const missing = (entry.input_names ?? []).filter((n) => !rows.some((r) => r.name === n))
  const failure = save.error ?? action.error ?? check.error

  return (
    <div className="page">
      <p>
        <Link to="/workshop">← Taller</Link>
      </p>
      <header className="page-head">
        <div>
          <h1>{entry.title}</h1>
          <p className="muted">Flujo de n8n {entry.workflow_id}</p>
        </div>
        <EntryStatusBadge status={entry.status} />
      </header>
      {entry.review_note && (
        <p className="notice notice-warning" role="status">
          Nota de la revisión: {entry.review_note}
        </p>
      )}
      {failure && (
        <p className="notice notice-error" role="alert">
          {errorMessage(failure)}
        </p>
      )}

      <section className="card">
        <h2>Lo que ve quien la lanza</h2>
        <fieldset className="stack" disabled={!editable}>
          <Field label="Título">
            <input maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Descripción">
            <textarea rows={3} maxLength={2000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <Field label="Área">
            <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as Category })}>
              {(Object.keys(CATEGORY) as Category[]).map((c) => (
                <option key={c} value={c}>
                  {CATEGORY[c]}
                </option>
              ))}
            </select>
          </Field>
        </fieldset>
      </section>

      <section className="card">
        <h2>Campos del formulario</h2>
        {missing.length > 0 && editable && (
          <p className="notice notice-info">
            El flujo usa {missing.map((n) => `«${n}»`).join(', ')}.{' '}
            <button
              type="button"
              className="btn-link"
              onClick={() => setRows([...rows, ...missing.map((n) => ({ name: n, label: n, type: 'text' as FieldType, required: false, options: '' }))])}
            >
              Añadirlos como campos
            </button>
          </p>
        )}
        {rows.length === 0 && <p className="muted">Sin campos: se lanza sin pedir datos.</p>}
        <fieldset className="stack" disabled={!editable}>
          {rows.map((r, i) => (
            <div className="toolbar" key={i}>
              <input aria-label={`Nombre del campo ${i + 1}`} placeholder="nombre" value={r.name} maxLength={64}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <input aria-label={`Etiqueta del campo ${i + 1}`} placeholder="etiqueta" className="grow" value={r.label} maxLength={100}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
              <select aria-label={`Tipo del campo ${i + 1}`} value={r.type}
                onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, type: e.target.value as FieldType } : x)))}>
                {(Object.keys(FIELD_TYPE) as FieldType[]).map((t) => (
                  <option key={t} value={t}>
                    {FIELD_TYPE[t]}
                  </option>
                ))}
              </select>
              {r.type === 'select' && (
                <input aria-label={`Opciones del campo ${i + 1}`} placeholder="opción 1, opción 2" value={r.options}
                  onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, options: e.target.value } : x)))} />
              )}
              <label className="check">
                <input type="checkbox" checked={r.required}
                  onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, required: e.target.checked } : x)))} />
                Obligatorio
              </label>
              <button type="button" className="btn btn-ghost btn-small" aria-label={`Quitar el campo ${i + 1}`}
                onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                Quitar
              </button>
            </div>
          ))}
        </fieldset>
        {editable && (
          <div className="actions">
            <button type="button" className="btn btn-ghost"
              onClick={() => setRows([...rows, { name: '', label: '', type: 'text', required: false, options: '' }])}>
              Añadir campo
            </button>
            <button type="button" className="btn btn-primary" disabled={save.isPending} onClick={() => save.mutate()}>
              Guardar
            </button>
          </div>
        )}
      </section>

      <section className="card">
        <h2>Comprobaciones</h2>
        <Checks entry={entry} />
        {entry.checked_at && <p className="muted">Última comprobación: {fmtDateTime(entry.checked_at)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" disabled={check.isPending} onClick={() => check.mutate()}>
            Comprobar el flujo
          </button>
          {entry.status === 'draft' && (
            <button type="button" className="btn btn-primary" disabled={action.isPending}
              onClick={() => action.mutate({ path: 'submit' })}>
              Enviar a revisión
            </button>
          )}
        </div>
      </section>

      {entry.status === 'in_review' && can('automations', 'manage') && (
        <section className="card">
          <h2>Revisión</h2>
          <Field label="Nota" hint="Opcional al publicar; explica qué falta si la devuelves.">
            <textarea rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <div className="actions">
            <button type="button" className="btn btn-ghost" disabled={action.isPending}
              onClick={() => action.mutate({ path: 'review', body: { decision: 'reject', note: note || null } })}>
              Devolver a borrador
            </button>
            <button type="button" className="btn btn-primary" disabled={action.isPending}
              onClick={() => action.mutate({ path: 'review', body: { decision: 'approve', note: note || null } })}>
              Publicar
            </button>
          </div>
        </section>
      )}
      {entry.status === 'in_review' && !can('automations', 'manage') && (
        <p className="notice notice-info">Pendiente de que quien administra la revise y la publique.</p>
      )}
      {entry.status === 'published' && can('automations', 'manage') && (
        <div className="actions">
          <button type="button" className="btn btn-danger-ghost" disabled={action.isPending}
            onClick={() => action.mutate({ path: 'retire' })}>
            Retirar del catálogo
          </button>
        </div>
      )}
    </div>
  )
}
