// Reglas de reparto de oportunidades (caso P18, ADR-020): a quién se asigna lo que llega solo
// (feeds, TED, buzón de pliegos). Las aplica la revisión horaria de oportunidades.
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtMoney } from '../lib/format'
import type { RoutingRule, RoutingRulesPage } from '../lib/types'
import { Badge, Empty, ErrorBox, Field, Modal, Spinner, errorMessage, useToast } from '../components/ui'
import { useServiceLines } from './Opportunities'

const KEY = ['opportunities', 'routing-rules']
const SOURCES: Record<string, string> = { ted: 'TED', buzon_pliegos: 'Buzón de pliegos' }

const splitList = (text: string) =>
  text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)

function criteria(rule: RoutingRule, lineNames: Record<string, string>): string {
  const parts: string[] = []
  if (rule.sources.length) parts.push(`Fuente: ${rule.sources.map((s) => SOURCES[s] ?? s).join(', ')}`)
  if (rule.service_lines.length) parts.push(`Línea: ${rule.service_lines.map((l) => lineNames[l] ?? l).join(', ')}`)
  if (rule.sectors.length) parts.push(`Sector: ${rule.sectors.join(', ')}`)
  if (rule.min_value_eur) parts.push(`Desde ${fmtMoney(rule.min_value_eur)}`)
  if (rule.max_value_eur) parts.push(`Hasta ${fmtMoney(rule.max_value_eur)}`)
  if (rule.max_days_to_deadline !== null) parts.push(`Plazo en ${rule.max_days_to_deadline} días o menos`)
  return parts.join(' · ') || 'Todas las oportunidades'
}

function RuleForm({ rule, page, onClose }: { rule: RoutingRule | null; page: RoutingRulesPage; onClose: () => void }) {
  const toast = useToast()
  const qc = useQueryClient()
  const lines = useServiceLines()
  const [form, setForm] = useState({
    name: rule?.name ?? '',
    position: String(rule?.position ?? 100),
    is_enabled: rule?.is_enabled ?? true,
    sources: rule?.sources ?? [],
    service_lines: rule?.service_lines ?? [],
    sectors: (rule?.sectors ?? []).join(', '),
    min_value_eur: rule?.min_value_eur ?? '',
    max_value_eur: rule?.max_value_eur ?? '',
    max_days_to_deadline: rule?.max_days_to_deadline === null || rule === null ? '' : String(rule.max_days_to_deadline),
    owner_user_id: String(rule?.owner_user_id ?? page.candidates[0]?.id ?? ''),
  })
  const toggle = (key: 'sources' | 'service_lines', value: string) =>
    setForm({ ...form, [key]: form[key].includes(value) ? form[key].filter((v) => v !== value) : [...form[key], value] })
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        position: Number(form.position) || 0,
        is_enabled: form.is_enabled,
        sources: form.sources,
        service_lines: form.service_lines,
        sectors: splitList(form.sectors),
        min_value_eur: form.min_value_eur || null,
        max_value_eur: form.max_value_eur || null,
        max_days_to_deadline: form.max_days_to_deadline === '' ? null : Number(form.max_days_to_deadline),
        owner_user_id: Number(form.owner_user_id),
      }
      return rule
        ? api<RoutingRule>(`/api/opportunities/routing-rules/${rule.id}`, { method: 'PUT', body: { ...body, version: rule.version } })
        : api<RoutingRule>('/api/opportunities/routing-rules', { body })
    },
    onSuccess: () => {
      toast('Regla guardada')
      void qc.invalidateQueries({ queryKey: KEY })
      onClose()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title={rule ? `Editar «${rule.name}»` : 'Nueva regla de reparto'} onClose={onClose} wide>
      <form className="stack" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Nombre">
            <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required maxLength={255} />
          </Field>
          <Field label="Responsable">
            <select value={form.owner_user_id} onChange={(e) => setForm({ ...form, owner_user_id: e.target.value })} required>
              {page.candidates.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Orden" hint="Se aplica la primera regla que encaje, de menor a mayor.">
            <input type="number" min={0} max={10000} value={form.position} onChange={(e) => setForm({ ...form, position: e.target.value })} />
          </Field>
          <Field label="Plazo en días o menos" hint="Vacío: cualquier plazo.">
            <input type="number" min={0} max={3650} value={form.max_days_to_deadline} onChange={(e) => setForm({ ...form, max_days_to_deadline: e.target.value })} />
          </Field>
          <Field label="Importe mínimo (€)">
            <input type="number" min={0} step="0.01" value={form.min_value_eur} onChange={(e) => setForm({ ...form, min_value_eur: e.target.value })} />
          </Field>
          <Field label="Importe máximo (€)">
            <input type="number" min={0} step="0.01" value={form.max_value_eur} onChange={(e) => setForm({ ...form, max_value_eur: e.target.value })} />
          </Field>
        </div>
        <fieldset className="stack">
          <legend>Fuente (ninguna marcada: todas)</legend>
          {Object.entries(SOURCES).map(([code, name]) => (
            <label key={code} className="check">
              <input type="checkbox" checked={form.sources.includes(code)} onChange={() => toggle('sources', code)} />
              {name}
            </label>
          ))}
        </fieldset>
        <fieldset className="stack">
          <legend>Línea de servicio (ninguna marcada: todas)</legend>
          {(lines.data?.items ?? []).map((l) => (
            <label key={l.code} className="check">
              <input type="checkbox" checked={form.service_lines.includes(l.code)} onChange={() => toggle('service_lines', l.code)} />
              {l.name}
            </label>
          ))}
        </fieldset>
        <Field label="Sectores" hint="Separados por comas. Vacío: todos.">
          <input value={form.sectors} onChange={(e) => setForm({ ...form, sectors: e.target.value })} />
        </Field>
        <label className="check">
          <input type="checkbox" checked={form.is_enabled} onChange={(e) => setForm({ ...form, is_enabled: e.target.checked })} />
          Activa
        </label>
        {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
        <div className="actions">
          <button type="button" className="btn" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={save.isPending || !form.owner_user_id}>
            Guardar
          </button>
        </div>
      </form>
    </Modal>
  )
}

function DeleteButton({ rule }: { rule: RoutingRule }) {
  const [sure, setSure] = useState(false)
  const toast = useToast()
  const qc = useQueryClient()
  const remove = useMutation({
    mutationFn: () => api<void>(`/api/opportunities/routing-rules/${rule.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast('Regla borrada')
      void qc.invalidateQueries({ queryKey: KEY })
    },
  })
  return sure ? (
    <button className="btn btn-danger" onClick={() => remove.mutate()} disabled={remove.isPending}>
      Confirmar borrado
    </button>
  ) : (
    <button className="btn" onClick={() => setSure(true)}>
      Borrar
    </button>
  )
}

export default function RoutingRules() {
  const lines = useServiceLines()
  const [editing, setEditing] = useState<RoutingRule | 'new' | null>(null)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: KEY,
    queryFn: () => api<RoutingRulesPage>('/api/opportunities/routing-rules'),
  })
  const lineNames = Object.fromEntries((lines.data?.items ?? []).map((l) => [l.code, l.name]))
  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/opportunities">Oportunidades</Link>
      </nav>
      <header className="page-head">
        <div>
          <h1>Reparto de oportunidades</h1>
          <p className="muted">
            A quién se asigna una oportunidad que llega sola (feeds, TED, buzón de pliegos). Cada hora, tras puntuarlas, se aplica
            la primera regla activa que encaje y se avisa a la persona. Las que ya tienen responsable no se tocan.
          </p>
        </div>
        {data && (
          <button className="btn btn-primary" onClick={() => setEditing('new')} disabled={!data.candidates.length}>
            Nueva regla
          </button>
        )}
      </header>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay reglas de reparto">Sin reglas, las oportunidades que llegan solas quedan sin responsable.</Empty>}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Orden</th>
                <th>Regla</th>
                <th>Responsable</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((r) => (
                <tr key={r.id}>
                  <td>{r.position}</td>
                  <td>
                    <span className="row-title">{r.name}</span>
                    <div className="row-sub">{criteria(r, lineNames)}</div>
                  </td>
                  <td>{r.owner_name ?? `#${r.owner_user_id}`}</td>
                  <td>{r.is_enabled ? <Badge tone="success">Activa</Badge> : <Badge>Apagada</Badge>}</td>
                  <td className="actions">
                    <button className="btn" onClick={() => setEditing(r)}>
                      Editar
                    </button>
                    <DeleteButton rule={r} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && data && <RuleForm rule={editing === 'new' ? null : editing} page={data} onClose={() => setEditing(null)} />}
    </div>
  )
}
