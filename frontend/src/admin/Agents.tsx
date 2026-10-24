// Agent Studio: los agentes del copiloto, con sus herramientas y su prompt.
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtRelative } from '../lib/format'
import type { Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Field, Modal, Pager, Spinner, errorMessage } from '../components/ui'
import { AGENT_STATUS } from './labels'
import type { Agent, AgentSummary } from './types'

export function AgentStatus({ status }: { status: string }) {
  return <Badge tone={status === 'active' ? 'success' : status === 'draft' ? 'warning' : 'neutral'}>{AGENT_STATUS[status] ?? status}</Badge>
}

export const AGENT_TYPES: Record<string, string> = { conversational: 'Conversacional', specialist: 'Especialista' }

function NewAgent({ onClose, onSaved }: { onClose: () => void; onSaved: (a: Agent) => void }) {
  const [form, setForm] = useState({ slug: '', name: '', description: '', agent_type: 'specialist', system_prompt: '' })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })
  const save = useMutation({
    mutationFn: () =>
      api<Agent>('/api/admin/agents', {
        body: { ...form, description: form.description || null, system_prompt: form.system_prompt || null },
      }),
    onSuccess: onSaved,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title="Nuevo agente" onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Nombre">
            <input value={form.name} onChange={set('name')} required maxLength={100} autoFocus />
          </Field>
          <Field label="Identificador" hint="Minúsculas y guion bajo. Su prompt se llamará agent.<identificador>.">
            <input value={form.slug} onChange={set('slug')} required pattern="[a-z][a-z0-9_]{1,49}" />
          </Field>
        </div>
        <Field label="Para qué sirve">
          <input value={form.description} onChange={set('description')} maxLength={500} />
        </Field>
        <Field label="Tipo">
          <select value={form.agent_type} onChange={set('agent_type')}>
            {Object.entries(AGENT_TYPES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Instrucciones" hint="Opcional: si lo dejas vacío, publica el prompt después desde Prompts.">
          <textarea className="mono" rows={8} value={form.system_prompt} onChange={set('system_prompt')} />
        </Field>
        <p className="field-hint">Se crea en borrador. Añade herramientas y pruébalo antes de activarlo.</p>
        {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Crear
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function Agents() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [creating, setCreating] = useState(false)
  const status = params.get('status') ?? ''
  const page = Number(params.get('page') ?? 1)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['admin', 'agents', status, page],
    queryFn: () => api<Page<AgentSummary>>('/api/admin/agents', { query: { status, page } }),
    placeholderData: keepPreviousData,
  })
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Agentes</h1>
          <p className="muted">
            Qué sabe hacer el copiloto: cada agente tiene un prompt y unas herramientas, y lo que cambia datos siempre pide
            aprobación.
          </p>
        </div>
        {can('agents', 'write') && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            Nuevo agente
          </button>
        )}
      </header>
      <div className="toolbar">
        <select value={status} onChange={(e) => setParams(e.target.value ? { status: e.target.value } : {})} aria-label="Estado">
          <option value="">Todos</option>
          {Object.entries(AGENT_STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay agentes" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Agente</th>
                <th>Tipo</th>
                <th>Estado</th>
                <th className="num">Herramientas</th>
                <th className="num">Versión</th>
                <th>Actualizado</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((a) => (
                <tr key={a.id}>
                  <td>
                    <Link to={`/agents/${a.id}`} className="row-title">
                      {a.name}
                    </Link>
                    <div className="row-sub">{a.description ?? a.slug}</div>
                  </td>
                  <td>{AGENT_TYPES[a.agent_type] ?? a.agent_type}</td>
                  <td>
                    <AgentStatus status={a.status} />
                  </td>
                  <td className="num">{a.tool_count}</td>
                  <td className="num">v{a.version_number}</td>
                  <td className="nowrap">{fmtRelative(a.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager pagination={data.pagination} onPage={(p) => setParams({ ...(status ? { status } : {}), page: String(p) })} />}
      {creating && <NewAgent onClose={() => setCreating(false)} onSaved={(a) => navigate(`/agents/${a.id}`)} />}
    </div>
  )
}
