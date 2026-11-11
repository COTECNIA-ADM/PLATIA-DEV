// Lanzar una automatización del catálogo con datos de entrada sencillos (clave → valor).
import { useState, type FormEvent } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router'
import { api } from '../lib/api'
import { Modal, errorMessage } from '../components/ui'
import type { RunDetail, Workflow } from './types'

type Row = { key: string; value: string }

const KEY = /^[A-Za-z_][A-Za-z0-9_]*$/

export default function Launch({ workflow, onClose }: { workflow: Workflow; onClose: () => void }) {
  const navigate = useNavigate()
  const [rows, setRows] = useState<Row[]>([{ key: '', value: '' }])
  const filled = rows.filter((r) => r.key.trim())
  const badKey = filled.find((r) => !KEY.test(r.key.trim()))
  const launch = useMutation({
    mutationFn: () =>
      api<RunDetail>('/api/automation/runs', {
        body: {
          workflow_id: workflow.id,
          input: Object.fromEntries(filled.map((r) => [r.key.trim(), r.value])),
        },
      }),
    onSuccess: (run) => navigate(`/runs/${run.id}`),
  })

  function update(i: number, patch: Partial<Row>) {
    setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!badKey) launch.mutate()
  }

  return (
    <Modal title={`Lanzar «${workflow.name}»`} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <p className="muted">
          Datos que recibirá la automatización. Déjalo vacío si no necesita ninguno. El resultado aparecerá en
          Ejecuciones.
        </p>
        {rows.map((row, i) => (
          <div className="grid-2" key={i}>
            <input
              aria-label={`Dato ${i + 1}`}
              placeholder="dato (p. ej. cliente)"
              value={row.key}
              maxLength={64}
              onChange={(e) => update(i, { key: e.target.value })}
            />
            <input
              aria-label={`Valor ${i + 1}`}
              placeholder="valor"
              value={row.value}
              maxLength={2000}
              onChange={(e) => update(i, { value: e.target.value })}
            />
          </div>
        ))}
        {badKey && (
          <p className="notice notice-warning" role="alert">
            «{badKey.key}» no vale como nombre de dato: usa letras, números y guion bajo, sin espacios.
          </p>
        )}
        {launch.error && (
          <p className="notice notice-error" role="alert">
            {errorMessage(launch.error)}
          </p>
        )}
        <div className="actions">
          {rows.length < 30 && (
            <button type="button" className="btn btn-ghost" onClick={() => setRows([...rows, { key: '', value: '' }])}>
              Añadir dato
            </button>
          )}
          <button type="submit" className="btn btn-primary" disabled={launch.isPending || !!badKey}>
            {launch.isPending ? 'Lanzando…' : 'Lanzar'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
