// Lanzar una automatización publicada: el formulario sale de los campos de su ficha.
import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { api } from '../lib/api'
import { Field, Modal, errorMessage } from '../components/ui'
import type { CatalogItem, FieldDef, RunDetail } from './types'

type Values = Record<string, string | boolean>

function initial(fields: FieldDef[]): Values {
  return Object.fromEntries(fields.map((f) => [f.name, f.type === 'boolean' ? false : '']))
}

/** Valores del formulario → datos de la API: números como número y vacíos fuera. */
export function toInput(fields: FieldDef[], values: Values): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of fields) {
    const v = values[f.name]
    if (f.type === 'boolean') out[f.name] = !!v
    else if (typeof v === 'string' && v.trim() !== '') out[f.name] = f.type === 'number' ? Number(v) : v.trim()
  }
  return out
}

function Input({ field, value, onChange }: { field: FieldDef; value: string | boolean; onChange: (v: string | boolean) => void }) {
  const common = { required: field.required }
  switch (field.type) {
    case 'textarea':
      return <textarea {...common} rows={4} maxLength={2000} value={value as string} onChange={(e) => onChange(e.target.value)} />
    case 'number':
      return <input {...common} type="number" step="any" value={value as string} onChange={(e) => onChange(e.target.value)} />
    case 'date':
      return <input {...common} type="date" value={value as string} onChange={(e) => onChange(e.target.value)} />
    case 'boolean':
      return <input type="checkbox" checked={value as boolean} onChange={(e) => onChange(e.target.checked)} />
    case 'select':
      return (
        <select {...common} value={value as string} onChange={(e) => onChange(e.target.value)}>
          <option value="">Elige…</option>
          {(field.options ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
      )
    default:
      return <input {...common} maxLength={300} value={value as string} onChange={(e) => onChange(e.target.value)} />
  }
}

export default function Launch({ item, onClose }: { item: CatalogItem; onClose: () => void }) {
  const navigate = useNavigate()
  const [values, setValues] = useState<Values>(() => initial(item.fields))
  const launch = useMutation({
    mutationFn: () =>
      api<RunDetail>('/api/automation/runs', { body: { entry_id: item.id, input: toInput(item.fields, values) } }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    launch.mutate()
  }

  return (
    <Modal title={`Lanzar «${item.title}»`} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        {item.description && <p className="muted">{item.description}</p>}
        {item.fields.length === 0 && <p>Esta automatización no necesita datos.</p>}
        {item.fields.map((f) => (
          <Field key={f.name} label={f.required ? `${f.label} *` : f.label} hint={f.help ?? undefined}>
            <Input field={f} value={values[f.name]} onChange={(v) => setValues({ ...values, [f.name]: v })} />
          </Field>
        ))}
        {launch.error && (
          <p className="notice notice-error" role="alert">
            {errorMessage(launch.error)}
          </p>
        )}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" className="btn btn-primary" disabled={launch.isPending}>
            {launch.isPending ? 'Lanzando…' : 'Lanzar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
