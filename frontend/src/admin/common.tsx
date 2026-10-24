// Piezas compartidas de la app de administración.
import { useMutation } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { Modal, errorMessage } from '../components/ui'

export type Confirm = { title: string; text: string; action: string; run: () => Promise<unknown>; danger?: boolean }

/** Confirmación antes de un cambio delicado; muestra el error sin cerrar si falla. */
export function ConfirmDialog({ confirm, onClose }: { confirm: Confirm; onClose: () => void }) {
  const run = useMutation({ mutationFn: confirm.run, onSuccess: onClose })
  return (
    <Modal title={confirm.title} onClose={onClose}>
      <div className="stack">
        <p>{confirm.text}</p>
        {run.error && <p className="notice notice-error">{errorMessage(run.error)}</p>}
        <div className="actions">
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className={`btn ${confirm.danger ? 'btn-danger' : 'btn-primary'}`} disabled={run.isPending} onClick={() => run.mutate()}>
            {confirm.action}
          </button>
        </div>
      </div>
    </Modal>
  )
}

/** Guarda un objeto como fichero JSON en el equipo. */
export function saveJson(name: string, data: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/** Pestaña activa guardada en la URL (?tab=), para poder enlazarla. */
export function useTab<T extends string>(tabs: readonly T[], param = 'tab'): [T, (t: T) => void] {
  const [params, setParams] = useSearchParams()
  const raw = params.get(param) as T | null
  const current = raw && tabs.includes(raw) ? raw : tabs[0]
  return [
    current,
    (t: T) => {
      const next = new URLSearchParams()
      next.set(param, t)
      setParams(next)
    },
  ]
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { key: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={t.key === value} className={`tab${t.key === value ? ' tab-on' : ''}`} onClick={() => onChange(t.key)}>
          {t.label}
        </button>
      ))}
    </div>
  )
}

/** Días hacia atrás para los informes de uso. */
export const DAY_OPTIONS = [7, 30, 90] as const

export function DaysPicker({ days, onChange }: { days: number; onChange: (d: number) => void }) {
  return (
    <select value={days} onChange={(e) => onChange(Number(e.target.value))} aria-label="Periodo">
      {DAY_OPTIONS.map((d) => (
        <option key={d} value={d}>
          Últimos {d} días
        </option>
      ))}
    </select>
  )
}

export function pct(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined) return '—'
  return `${(value * 100).toLocaleString('es-ES', { maximumFractionDigits: digits })} %`
}
