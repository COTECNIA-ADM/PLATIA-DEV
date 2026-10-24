// Objetivos comerciales e importación desde Excel (fase 9a).
// Los objetivos son mensuales, por métrica y, opcionalmente, por línea de servicio. El
// cuadro de mando los compara con lo real. La importación primero comprueba el fichero
// (sin guardar nada) y solo aplica si no hay errores.
import { useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { api, download } from '../lib/api'
import { useAuth } from '../lib/auth'
import type { Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Field, Modal, Spinner, errorMessage, useToast } from '../components/ui'
import { TARGET_METRICS, fmtMetric, isMoneyMetric, monthLabel, useServiceLines } from './common'
import type { ImportResult, Target, TargetMetric } from './types'

const SHEET_NAMES: Record<string, string> = { competidores: 'Competidores', objetivos: 'Objetivos' }

export default function Targets() {
  const { can } = useAuth()
  const { names } = useServiceLines()
  const [params, setParams] = useSearchParams()
  const thisYear = new Date().getFullYear()
  const year = Number(params.get('year') ?? thisYear)
  const [open, setOpen] = useState<Target | 'new' | null>(null)
  const queryClient = useQueryClient()
  const toast = useToast()
  const canWrite = can('dashboards', 'write')
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['analytics', 'targets', year],
    queryFn: () => api<Page<Target>>('/api/analytics/targets', { query: { year, per_page: 100 } }),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`/api/analytics/targets/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast('Objetivo borrado.', 'success')
      void queryClient.invalidateQueries({ queryKey: ['analytics'] })
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Objetivos e importación</h1>
          <p className="muted">Objetivos mensuales que el cuadro de mando compara con lo real, y carga de datos desde Excel.</p>
        </div>
        {canWrite && (
          <button className="btn btn-primary" onClick={() => setOpen('new')}>
            Nuevo objetivo
          </button>
        )}
      </header>

      <section className="card">
        <header className="card-head">
          <h2>Objetivos de {year}</h2>
          <select value={year} onChange={(e) => setParams({ year: e.target.value }, { replace: true })} aria-label="Año">
            {[thisYear + 1, thisYear, thisYear - 1, thisYear - 2].map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </header>
        {isLoading && <Spinner />}
        {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
        {data && !data.items.length && <Empty title={`No hay objetivos en ${year}`} />}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Mes</th>
                  <th>Métrica</th>
                  <th>Línea</th>
                  <th className="num">Objetivo</th>
                  {canWrite && <th />}
                </tr>
              </thead>
              <tbody>
                {data.items.map((t) => (
                  <tr key={t.id}>
                    <td>{monthLabel(t.period)}</td>
                    <td>{TARGET_METRICS[t.metric]}</td>
                    <td>{t.service_line ? (names[t.service_line] ?? t.service_line) : <span className="muted">Total</span>}</td>
                    <td className="num">{fmtMetric(t.metric, t.target_value)}</td>
                    {canWrite && (
                      <td className="num">
                        <button className="btn btn-small btn-ghost" onClick={() => setOpen(t)}>
                          Editar
                        </button>
                        <button
                          className="btn btn-small btn-ghost"
                          disabled={remove.isPending}
                          onClick={() => window.confirm('¿Borrar el objetivo?') && remove.mutate(t.id)}
                        >
                          Borrar
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.pagination.total > data.items.length && (
          <p className="muted small">Se muestran {data.items.length} de {data.pagination.total}.</p>
        )}
      </section>

      {canWrite && <ImportCard />}
      {open && <TargetForm target={open === 'new' ? undefined : open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function TargetForm({ target, onClose }: { target?: Target; onClose: () => void }) {
  const { lines } = useServiceLines()
  const queryClient = useQueryClient()
  const toast = useToast()
  const now = new Date()
  const [form, setForm] = useState({
    metric: (target?.metric ?? 'won_eur') as TargetMetric,
    period: target?.period ?? `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`,
    service_line: target?.service_line ?? '',
    target_value: target ? String(Number(target.target_value)) : '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value })
  const save = useMutation({
    mutationFn: () =>
      target
        ? api<Target>(`/api/analytics/targets/${target.id}`, {
            method: 'PATCH',
            body: { target_value: form.target_value, version: target.version },
          })
        : api<Target>('/api/analytics/targets', { body: form }),
    onSuccess: () => {
      toast('Objetivo guardado.', 'success')
      void queryClient.invalidateQueries({ queryKey: ['analytics'] })
      onClose()
    },
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title={target ? 'Editar objetivo' : 'Nuevo objetivo'} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <div className="grid-2">
          <Field label="Métrica">
            <select value={form.metric} onChange={set('metric')} disabled={!!target}>
              {Object.entries(TARGET_METRICS).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Mes">
            <input type="month" value={form.period} onChange={set('period')} required disabled={!!target} />
          </Field>
          <Field label="Línea de servicio" hint="Vacío: objetivo total de la empresa">
            <select value={form.service_line} onChange={set('service_line')} disabled={!!target}>
              <option value="">Total</option>
              {lines.map((l) => (
                <option key={l.code} value={l.code}>
                  {l.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label={isMoneyMetric(form.metric) ? 'Objetivo (€)' : 'Objetivo (número)'}>
            <input
              type="number"
              min={0}
              step={isMoneyMetric(form.metric) ? '0.01' : '1'}
              value={form.target_value}
              onChange={set('target_value')}
              required
              autoFocus
            />
          </Field>
        </div>
        {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Guardar
          </button>
        </div>
      </form>
    </Modal>
  )
}

function ImportCard() {
  const fileRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const queryClient = useQueryClient()
  const toast = useToast()
  const run = useMutation({
    mutationFn: (dryRun: boolean) => {
      const form = new FormData()
      form.append('file', file!)
      return api<ImportResult>('/api/analytics/import', { form, query: { dry_run: dryRun } })
    },
    onSuccess: (result) => {
      if (result.applied) {
        toast('Datos importados.', 'success')
        void queryClient.invalidateQueries({ queryKey: ['analytics'] })
      }
    },
  })
  const template = useMutation({
    mutationFn: () => download('/api/analytics/import/template', 'plantilla-analitica.xlsx'),
    onError: (e) => toast(errorMessage(e), 'danger'),
  })
  const result = run.data

  function reset() {
    setFile(null)
    run.reset()
    if (fileRef.current) fileRef.current.value = ''
  }

  return (
    <section className="card section-gap">
      <header className="card-head">
        <h2>Importar desde Excel</h2>
        <button className="btn btn-small" onClick={() => template.mutate()} disabled={template.isPending}>
          Descargar plantilla
        </button>
      </header>
      <p className="muted">
        La plantilla tiene una hoja de competidores y otra de objetivos (puedes rellenar solo una). Primero se comprueba el
        fichero sin guardar nada; si no hay errores, confirmas la importación. Un competidor con el mismo nombre o un
        objetivo con la misma métrica, mes y línea se actualiza.
      </p>
      <div className="toolbar">
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          onChange={(e) => {
            run.reset()
            setFile(e.target.files?.[0] ?? null)
          }}
          aria-label="Fichero Excel"
        />
        <button className="btn" disabled={!file || run.isPending} onClick={() => run.mutate(true)}>
          {run.isPending && run.variables ? 'Comprobando…' : 'Comprobar'}
        </button>
      </div>
      {run.error && <p className="notice notice-error">{errorMessage(run.error)}</p>}
      {result && (
        <div className="stack">
          <table className="table table-compact">
            <thead>
              <tr>
                <th>Hoja</th>
                <th className="num">Filas</th>
                <th className="num">Nuevos</th>
                <th className="num">Actualizados</th>
                <th className="num">Errores</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(result.sheets).map(([name, s]) => (
                <tr key={name}>
                  <td>{SHEET_NAMES[name] ?? name}</td>
                  <td className="num">{s.rows}</td>
                  <td className="num">{s.create}</td>
                  <td className="num">{s.update}</td>
                  <td className="num">{s.error_count ? <Badge tone="danger">{s.error_count}</Badge> : 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {result.has_errors && (
            <div className="import-errors">
              <p className="notice notice-error">Corrige estos errores en el Excel y vuelve a comprobarlo. No se ha guardado nada.</p>
              <table className="table table-compact">
                <thead>
                  <tr>
                    <th>Hoja</th>
                    <th className="num">Fila</th>
                    <th>Columna</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(result.sheets).flatMap(([name, s]) =>
                    s.errors.map((err, i) => (
                      <tr key={`${name}-${i}`}>
                        <td>{SHEET_NAMES[name] ?? name}</td>
                        <td className="num">{err.row}</td>
                        <td>{err.field ?? '—'}</td>
                        <td>{err.message}</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          )}
          {result.applied && <p className="notice notice-success">Importación hecha.</p>}
          <div className="actions">
            <button className="btn btn-ghost" onClick={reset}>
              {result.applied ? 'Importar otro fichero' : 'Cancelar'}
            </button>
            {result.dry_run && !result.has_errors && (
              <button className="btn btn-primary" disabled={run.isPending} onClick={() => run.mutate(false)}>
                Importar
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
