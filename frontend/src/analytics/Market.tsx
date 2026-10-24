// Mapa de oportunidad (fase 9a): puntuación 0-100 por sector × línea de servicio, con
// el detalle de cada celda y los pesos de las cuatro dimensiones.
import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { ApiError, api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { SECTORS, fmtDateTime, fmtMoney } from '../lib/format'
import { ChartCard, Heatmap } from '../components/charts'
import { Empty, ErrorBox, Field, Modal, Spinner, errorMessage, useToast } from '../components/ui'
import { downloadCsv, monthLabel } from './common'
import type { Dimension, MarketCell, MarketMap } from './types'

const DIMENSIONS: { key: Dimension; label: string; help: string }[] = [
  { key: 'demand', label: 'Demanda', help: 'Cuántas oportunidades aparecen en el cruce' },
  { key: 'traction', label: 'Tracción', help: 'Si crece: mitad reciente frente a la anterior' },
  { key: 'economic', label: 'Valor económico', help: 'Importe medio de las oportunidades' },
  { key: 'right_to_win', label: 'Capacidad de ganar', help: 'Tasa de éxito, suavizada con pocos cierres' },
]

const sectorName = (code: string) => SECTORS[code] ?? code
const score = (n: number) => n.toLocaleString('es-ES', { maximumFractionDigits: 0 })

export default function Market() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const period = params.get('period') ?? ''
  const [selected, setSelected] = useState<{ row: string; col: string } | null>(null)
  const [editing, setEditing] = useState(false)
  const toast = useToast()
  const queryClient = useQueryClient()
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['analytics', 'heatmap', period],
    queryFn: () => api<MarketMap>('/api/analytics/heatmap', { query: { period } }),
  })
  const recalc = useMutation({
    mutationFn: () => api('/api/analytics/heatmap/recalculate', { method: 'POST' }),
    onSuccess: () => {
      toast('Mapa recalculado con los datos de hoy.', 'success')
      void queryClient.invalidateQueries({ queryKey: ['analytics', 'heatmap'] })
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })

  if (isLoading) return <Spinner />
  if (error && !(error instanceof ApiError && error.status === 404)) return <ErrorBox error={error} onRetry={() => void refetch()} />

  const cells = data?.cells ?? []
  const sectors = [...new Set(cells.map((c) => c.sector))].sort((a, b) => sectorName(a).localeCompare(sectorName(b)))
  const lines = [...new Map(cells.map((c) => [c.service_line, c.service_line_label])).entries()].sort((a, b) =>
    a[1].localeCompare(b[1]),
  )
  const find = (s: string, l: string) => cells.find((c) => c.sector === s && c.service_line === l)
  const detail = selected ? find(selected.row, selected.col) : cells[0]
  const canWrite = can('dashboards', 'write')

  function setPeriod(value: string) {
    setSelected(null)
    setParams(value ? { period: value } : {}, { replace: true })
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Mapa de oportunidad</h1>
          <p className="muted">
            Dónde conviene invertir el esfuerzo comercial: cada cruce de sector y línea puntúa de 0 a 100 frente al resto.
          </p>
        </div>
        {canWrite && (
          <div className="btn-row">
            <button className="btn" onClick={() => setEditing(true)} disabled={!data}>
              Pesos
            </button>
            <button className="btn btn-primary" onClick={() => recalc.mutate()} disabled={recalc.isPending}>
              {recalc.isPending ? 'Recalculando…' : 'Recalcular'}
            </button>
          </div>
        )}
      </header>

      <div className="toolbar">
        <select value={period || data?.period || ''} onChange={(e) => setPeriod(e.target.value)} aria-label="Mes">
          {!data && <option value={period}>{period ? monthLabel(period) : 'Mes en curso'}</option>}
          {(data?.periods ?? []).map((p) => (
            <option key={p} value={p}>
              {monthLabel(p)}
            </option>
          ))}
        </select>
        {data && (
          <span className="muted small">
            Calculado el {fmtDateTime(data.calculated_at)} con {data.lookback_months ?? '—'} meses de datos
            {data.unclassified ? ` · ${data.unclassified} oportunidades sin sector o sin línea no puntúan` : ''}
          </span>
        )}
        <div className="grow" />
        {data && (
          <button
            className="btn btn-small"
            onClick={() =>
              downloadCsv(
                `mapa-oportunidad-${data.period}.csv`,
                ['Sector', 'Línea', 'Puntuación', ...DIMENSIONS.map((d) => d.label), 'Oportunidades', 'Ganadas', 'Perdidas', 'Importe medio (€)', 'Cartera (€)'],
                cells.map((c) => [
                  sectorName(c.sector),
                  c.service_line_label,
                  c.total_score,
                  ...DIMENSIONS.map((d) => c.scores[d.key]),
                  c.data.opportunities,
                  c.data.won,
                  c.data.lost,
                  c.data.avg_value_eur,
                  c.data.pipeline_eur,
                ]),
              )
            }
          >
            Descargar CSV
          </button>
        )}
      </div>

      {!data || !cells.length ? (
        <Empty title={data ? 'No hay oportunidades clasificadas en este periodo' : 'Este mes no tiene puntuaciones'}>
          {error ? errorMessage(error) : 'Hacen falta oportunidades con sector y línea de servicio.'}
        </Empty>
      ) : (
        <div className="market-grid">
          <ChartCard
            title="Puntuación por sector y línea"
            subtitle="Elige una celda para ver de dónde sale su puntuación"
            table={<ScoreTable cells={cells} />}
          >
            <Heatmap
              rows={sectors.map((s) => ({ key: s, label: sectorName(s) }))}
              cols={lines.map(([key, name]) => ({ key, label: name }))}
              cell={(s, l) => {
                const c = find(s, l)
                return c && { value: c.total_score, detail: `${c.data.opportunities} oportunidades` }
              }}
              format={score}
              max={100}
              onSelect={(row, col) => setSelected({ row, col })}
              selected={selected ?? (detail ? { row: detail.sector, col: detail.service_line } : null)}
            />
          </ChartCard>
          {detail && <CellDetail cell={detail} weights={data.weights} />}
        </div>
      )}

      {editing && data && (
        <WeightsForm
          config={data.config}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false)
            toast('Pesos guardados; el mes en curso se ha recalculado.', 'success')
            void queryClient.invalidateQueries({ queryKey: ['analytics', 'heatmap'] })
          }}
        />
      )}
    </div>
  )
}

function CellDetail({ cell, weights }: { cell: MarketCell; weights: Record<Dimension, number> }) {
  const d = cell.data
  return (
    <section className="card">
      <h2>
        {sectorName(cell.sector)} · {cell.service_line_label}
      </h2>
      <p className="stat-value">{score(cell.total_score)} / 100</p>
      <div className="dims">
        {DIMENSIONS.map((dim) => (
          <div key={dim.key} title={dim.help}>
            <span>
              {dim.label} <span className="muted small">({weights[dim.key] ?? 0} %)</span>
            </span>
            <span className="progress" aria-hidden="true">
              <span className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, cell.scores[dim.key]))}%` }} />
            </span>
            <span className="num">{score(cell.scores[dim.key])}</span>
          </div>
        ))}
      </div>
      <dl className="facts">
        <dt>Oportunidades</dt>
        <dd>
          {d.opportunities} ({d.prior} en la primera mitad, {d.recent} en la segunda)
        </dd>
        <dt>Ganadas / perdidas</dt>
        <dd>
          {d.won} / {d.lost}
        </dd>
        <dt>Importe medio</dt>
        <dd>{d.avg_value_eur === null ? '—' : fmtMoney(d.avg_value_eur)}</dd>
        <dt>Cartera abierta</dt>
        <dd>{fmtMoney(d.pipeline_eur)}</dd>
      </dl>
      <p className="muted small">
        Las puntuaciones son relativas: 100 es el mejor cruce del mes en esa dimensión, no un valor absoluto.
      </p>
    </section>
  )
}

function ScoreTable({ cells }: { cells: MarketCell[] }) {
  return (
    <table className="table table-compact">
      <thead>
        <tr>
          <th>Sector</th>
          <th>Línea</th>
          <th className="num">Total</th>
          {DIMENSIONS.map((d) => (
            <th key={d.key} className="num">
              {d.label}
            </th>
          ))}
          <th className="num">Oportunidades</th>
        </tr>
      </thead>
      <tbody>
        {cells.map((c) => (
          <tr key={`${c.sector}|${c.service_line}`}>
            <td>{sectorName(c.sector)}</td>
            <td>{c.service_line_label}</td>
            <td className="num">{score(c.total_score)}</td>
            {DIMENSIONS.map((d) => (
              <td key={d.key} className="num">
                {score(c.scores[d.key])}
              </td>
            ))}
            <td className="num">{c.data.opportunities}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function WeightsForm({
  config,
  onClose,
  onSaved,
}: {
  config: MarketMap['config']
  onClose: () => void
  onSaved: () => void
}) {
  const [weights, setWeights] = useState<Record<Dimension, number>>(config.weights)
  const [lookback, setLookback] = useState(config.lookback_months)
  const total = DIMENSIONS.reduce((sum, d) => sum + (weights[d.key] || 0), 0)
  const save = useMutation({
    mutationFn: () =>
      api('/api/analytics/heatmap/config', {
        method: 'PUT',
        body: {
          weight_demand: weights.demand,
          weight_traction: weights.traction,
          weight_economic: weights.economic,
          weight_right_to_win: weights.right_to_win,
          lookback_months: lookback,
          version: config.version,
        },
      }),
    onSuccess: onSaved,
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title="Pesos del mapa de oportunidad" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <p className="muted">Cuánto cuenta cada dimensión en la puntuación total. Deben sumar 100.</p>
        <div className="weights">
          {DIMENSIONS.map((d) => (
            <Field key={d.key} label={`${d.label} (%)`} hint={d.help}>
              <input
                type="number"
                min={0}
                max={100}
                step={5}
                value={weights[d.key]}
                onChange={(e) => setWeights({ ...weights, [d.key]: Number(e.target.value) })}
                required
              />
            </Field>
          ))}
        </div>
        <p className={total === 100 ? 'muted' : 'notice notice-error'}>Suma: {total} %</p>
        <Field label="Meses de datos" hint="Ventana que se analiza hacia atrás (de 3 a 36)">
          <input type="number" min={3} max={36} value={lookback} onChange={(e) => setLookback(Number(e.target.value))} required />
        </Field>
        {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={save.isPending || total !== 100}>
            Guardar y recalcular
          </button>
        </div>
      </form>
    </Modal>
  )
}
