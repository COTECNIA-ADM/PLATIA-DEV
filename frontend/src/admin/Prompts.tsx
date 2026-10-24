// Prompts: viven en la base de datos y se versionan. Aquí se ven los activos.
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtRelative } from '../lib/format'
import { Badge, Empty, ErrorBox, Field, Modal, Spinner, errorMessage, useDebounced } from '../components/ui'
import { SERVICE_TYPES } from '../analytics/AIValue'
import type { Prompt } from './types'

function NewPrompt({ onClose, onSaved }: { onClose: () => void; onSaved: (p: Prompt) => void }) {
  const [form, setForm] = useState({ name: '', description: '', system_prompt: '', user_template: '' })
  const save = useMutation({
    mutationFn: () =>
      api<Prompt>('/api/admin/ai/prompts', {
        body: { ...form, description: form.description || null, user_template: form.user_template || null, notes: 'Primera versión' },
      }),
    onSuccess: onSaved,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title="Nuevo prompt" onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        <Field label="Nombre" hint="Minúsculas y guiones bajos, en partes separadas por puntos (p. ej. proposal.summary). Los de un agente se llaman agent.<slug>.">
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required pattern="[a-z0-9_]+(\.[a-z0-9_]+)+" autoFocus />
        </Field>
        <Field label="Descripción">
          <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} maxLength={500} />
        </Field>
        <Field label="Instrucciones de sistema">
          <textarea className="mono" rows={10} value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} required />
        </Field>
        <Field label="Plantilla del usuario" hint="Las variables se escriben {{variable}} y van aquí, no en las instrucciones de sistema.">
          <textarea className="mono" rows={6} value={form.user_template} onChange={(e) => setForm({ ...form, user_template: e.target.value })} />
        </Field>
        {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Publicar
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function Prompts() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [creating, setCreating] = useState(false)
  const q = useDebounced(text.trim().toLowerCase(), 150)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['admin', 'prompts'],
    queryFn: () => api<{ items: Prompt[] }>('/api/admin/ai/prompts'),
  })
  const items = data?.items.filter((p) => !q || p.name.includes(q) || (p.description ?? '').toLowerCase().includes(q)) ?? []
  const broken = data?.items.filter((p) => p.integrity_ok === false) ?? []

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Prompts</h1>
          <p className="muted">
            Las instrucciones que recibe cada modelo. Cada cambio publica una versión nueva; puedes volver a una anterior en
            cualquier momento.
          </p>
        </div>
        {can('prompts', 'write') && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            Nuevo prompt
          </button>
        )}
      </header>
      {broken.length > 0 && (
        <p className="notice notice-error">
          Estos prompts se han modificado en la base de datos sin pasar por aquí: {broken.map((p) => p.name).join(', ')}. Revisa
          su contenido y publica una versión nueva.
        </p>
      )}
      <div className="toolbar">
        <input type="search" className="grow" placeholder="Filtrar por nombre" value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !items.length && <Empty title="No hay prompts que coincidan" />}
      {items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Prompt</th>
                <th>Tarea</th>
                <th>Variables</th>
                <th className="num">Versión</th>
                <th>Publicada</th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.name}>
                  <td>
                    <Link to={`/prompts/${encodeURIComponent(p.name)}`} className="row-title">
                      <code>{p.name}</code>
                    </Link>
                    {p.integrity_ok === false && <Badge tone="danger">Modificado fuera</Badge>}
                    {p.description && <div className="row-sub">{p.description}</div>}
                  </td>
                  <td>{p.service_type ? SERVICE_TYPES[p.service_type] ?? p.service_type : '—'}</td>
                  <td>
                    <span className="tag-list">
                      {p.variables.map((v) => (
                        <code key={v} className="tag">
                          {v}
                        </code>
                      ))}
                    </span>
                  </td>
                  <td className="num">v{p.version}</td>
                  <td className="nowrap">{fmtRelative(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <NewPrompt onClose={() => setCreating(false)} onSaved={(p) => navigate(`/prompts/${encodeURIComponent(p.name)}`)} />}
    </div>
  )
}
