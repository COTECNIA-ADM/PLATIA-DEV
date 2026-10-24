// Un prompt: sus versiones, publicar una nueva, volver a una anterior y probar el render.
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime } from '../lib/format'
import { Badge, ErrorBox, Field, Spinner, errorMessage, useToast } from '../components/ui'
import { SERVICE_TYPES } from '../analytics/AIValue'
import type { Prompt } from './types'

type Preview = { name: string; version: number; system: string; user: string | null; placeholders: string[] }

function Editor({ base, onDone }: { base: Prompt; onDone: () => void }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({ system_prompt: base.system_prompt ?? '', user_template: base.user_template ?? '', notes: '', activate: true })
  const save = useMutation({
    mutationFn: () =>
      api<Prompt>('/api/admin/ai/prompts', {
        body: {
          name: base.name,
          system_prompt: form.system_prompt,
          user_template: form.user_template || null,
          notes: form.notes || null,
          description: base.description,
          service_type: base.service_type,
          activate: form.activate,
        },
      }),
    onSuccess: (p) => {
      toast(p.is_active ? `Publicada y activa la versión ${p.version}.` : `Guardada la versión ${p.version} sin activar.`)
      void qc.invalidateQueries({ queryKey: ['admin', 'prompt', base.name] })
      void qc.invalidateQueries({ queryKey: ['admin', 'prompts'] })
      onDone()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <form className="card stack" onSubmit={submit}>
      <h2>Nueva versión (a partir de la v{base.version})</h2>
      <Field label="Instrucciones de sistema">
        <textarea className="mono" rows={14} value={form.system_prompt} onChange={(e) => setForm({ ...form, system_prompt: e.target.value })} required />
      </Field>
      <Field label="Plantilla del usuario" hint="Las variables van entre llaves dobles: {{variable}}.">
        <textarea className="mono" rows={8} value={form.user_template} onChange={(e) => setForm({ ...form, user_template: e.target.value })} />
      </Field>
      <Field label="Qué cambia" hint="Queda en el historial de versiones.">
        <input value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} maxLength={500} />
      </Field>
      <label className="check">
        <input type="checkbox" checked={form.activate} onChange={(e) => setForm({ ...form, activate: e.target.checked })} />
        Activarla al publicar (si no, queda guardada para activarla después)
      </label>
      {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
      <div className="actions">
        <button type="button" className="btn btn-ghost" onClick={onDone}>
          Cancelar
        </button>
        <button className="btn btn-primary" disabled={save.isPending}>
          Publicar
        </button>
      </div>
    </form>
  )
}

function PreviewBox({ prompt }: { prompt: Prompt }) {
  const [values, setValues] = useState<Record<string, string>>({})
  const run = useMutation({
    mutationFn: () => api<Preview>(`/api/admin/ai/prompts/${encodeURIComponent(prompt.name)}/preview`, { body: { variables: values } }),
  })
  return (
    <section className="card stack">
      <h2>Probar con datos de ejemplo</h2>
      <p className="muted">Muestra el texto que recibiría el modelo con la versión activa. No llama al modelo.</p>
      {prompt.variables.map((v) => (
        <Field key={v} label={v}>
          <textarea rows={2} value={values[v] ?? ''} onChange={(e) => setValues({ ...values, [v]: e.target.value })} />
        </Field>
      ))}
      <div className="actions">
        <button className="btn" disabled={run.isPending} onClick={() => run.mutate()}>
          Ver resultado
        </button>
      </div>
      {run.error && <p className="notice notice-error">{errorMessage(run.error)}</p>}
      {run.data && (
        <>
          {run.data.placeholders.length > 0 && (
            <p className="field-hint">Sin valor (se muestran entre &lt;&gt;): {run.data.placeholders.join(', ')}</p>
          )}
          <h3>Sistema</h3>
          <pre className="code-block">{run.data.system}</pre>
          {run.data.user && (
            <>
              <h3>Usuario</h3>
              <pre className="code-block">{run.data.user}</pre>
            </>
          )}
        </>
      )}
    </section>
  )
}

export default function PromptDetail() {
  const { name = '' } = useParams()
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [selected, setSelected] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['admin', 'prompt', name],
    queryFn: () => api<{ items: Prompt[] }>(`/api/admin/ai/prompts/${encodeURIComponent(name)}/versions`),
  })
  const activate = useMutation({
    mutationFn: (version: number) => api<Prompt>(`/api/admin/ai/prompts/${encodeURIComponent(name)}/versions/${version}/activate`, { method: 'POST' }),
    onSuccess: (p) => {
      toast(`Activa la versión ${p.version}.`)
      void qc.invalidateQueries({ queryKey: ['admin', 'prompt', name] })
      void qc.invalidateQueries({ queryKey: ['admin', 'prompts'] })
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!data?.items.length) return null
  const versions = data.items
  const active = versions.find((v) => v.is_active) ?? versions[0]
  const shown = versions.find((v) => v.version === selected) ?? active
  const canWrite = can('prompts', 'write')

  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/prompts">Prompts</Link> / {name}
      </nav>
      <header className="page-head">
        <div>
          <h1>
            <code>{name}</code>
          </h1>
          <p className="muted">
            {active.description ?? 'Sin descripción'}
            {active.service_type && ` · ${SERVICE_TYPES[active.service_type] ?? active.service_type}`}
          </p>
        </div>
        {canWrite && !editing && (
          <button className="btn btn-primary" onClick={() => setEditing(true)}>
            Editar
          </button>
        )}
      </header>

      {editing ? (
        <Editor base={shown} onDone={() => setEditing(false)} />
      ) : (
        <div className="detail-grid">
          <div className="stack">
            <section className="card">
              <header className="card-head">
                <h2>
                  Versión {shown.version} {shown.is_active ? <Badge tone="success">Activa</Badge> : <Badge>Inactiva</Badge>}
                </h2>
                {canWrite && !shown.is_active && (
                  <button className="btn btn-small" disabled={activate.isPending} onClick={() => activate.mutate(shown.version)}>
                    Activar esta versión
                  </button>
                )}
              </header>
              {shown.notes && <p className="muted">{shown.notes}</p>}
              <h3>Sistema</h3>
              <pre className="code-block">{shown.system_prompt}</pre>
              {shown.user_template && (
                <>
                  <h3>Plantilla del usuario</h3>
                  <pre className="code-block">{shown.user_template}</pre>
                </>
              )}
              <p className="field-hint">
                Huella <code>{shown.content_hash.slice(0, 12)}</code>: si alguien cambia el texto en la base de datos sin pasar por
                aquí, no coincidirá y saldrá un aviso.
              </p>
            </section>
            <PreviewBox prompt={active} />
          </div>
          <aside className="card">
            <h2>Versiones</h2>
            <ul className="plain-list version-list">
              {versions.map((v) => (
                <li key={v.version}>
                  <button className={`version-item${v.version === shown.version ? ' version-on' : ''}`} onClick={() => setSelected(v.version)}>
                    <span>
                      v{v.version} {v.is_active && <Badge tone="success">activa</Badge>}
                    </span>
                    <span className="row-sub">{fmtDateTime(v.created_at)}</span>
                    {v.notes && <span className="row-sub">{v.notes}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      )}
    </div>
  )
}
