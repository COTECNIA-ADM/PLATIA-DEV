// Cuadro de mando de negocio: cartera, embudo, tendencia, líneas de servicio y sectores.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { api } from '../lib/api'
import { PHASES, PROPOSAL_STATUS, SECTORS, fmtMoney, label } from '../lib/format'
import { BarList, ChartCard, ColumnChart, Heatmap, compact, type Series } from '../components/charts'
import { Empty, ErrorBox, Spinner, Stat } from '../components/ui'
import { PeriodPicker, downloadCsv, monthLabel, pct, usePeriod } from './common'
import type { Overview } from './types'

const TREND: Series[] = [
  { key: 'new', label: 'Nuevas', color: 'var(--series-1)' },
  { key: 'won', label: 'Ganadas', color: 'var(--series-2)' },
  { key: 'lost', label: 'Perdidas', color: 'var(--series-3)' },
]

const money = (n: number) => fmtMoney(n)
const sectorName = (code: string) => SECTORS[code] ?? code

/** El backend devuelve el código del sector; el nombre legible vive en el frontal. */
function withSectorNames(d: Overview): Overview {
  return { ...d, by_sector: d.by_sector.map((g) => ({ ...g, label: SECTORS[g.key] ?? g.label })) }
}
const moneyShort = (n: number) => `${compact(n)} €`

export default function Dashboard() {
  const [months, setMonths] = usePeriod()
  const [params, setParams] = useSearchParams()
  const line = params.get('service_line') ?? ''
  const sector = params.get('sector') ?? ''
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['analytics', 'overview', months, line, sector],
    queryFn: () => api<Overview>('/api/analytics/overview', { query: { months, service_line: line, sector } }).then(withSectorNames),
    placeholderData: keepPreviousData,
  })
  // Las opciones de los filtros salen del periodo completo, sin filtrar
  const options = useQuery({
    queryKey: ['analytics', 'options', months],
    queryFn: () => api<Overview>('/api/analytics/overview', { query: { months } }).then(withSectorNames),
    enabled: !!(line || sector),
    placeholderData: keepPreviousData,
  }).data ?? (line || sector ? undefined : data)

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!data) return null
  const k = data.kpis
  const funnelMax = data.funnel[0]?.reached ?? 0
  const sectors = [...new Set(data.heatmap.map((c) => c.sector))].sort((a, b) => sectorName(a).localeCompare(sectorName(b)))
  const lines = [...new Map(data.heatmap.map((c) => [c.service_line, c.service_line_label])).entries()].sort((a, b) =>
    a[1].localeCompare(b[1]),
  )

  return (
    <div className={`page${isFetching ? ' is-refreshing' : ''}`}>
      <header className="page-head">
        <div>
          <h1>Cuadro de mando</h1>
          <p className="muted">Cartera, conversión y resultados del equipo comercial.</p>
        </div>
      </header>

      <div className="toolbar">
        <PeriodPicker months={months} onChange={setMonths} />
        <select value={line} onChange={(e) => setFilter('service_line', e.target.value)} aria-label="Línea de servicio">
          <option value="">Todas las líneas</option>
          {options?.by_service_line.map((g) => (
            <option key={g.key} value={g.key}>
              {g.label}
            </option>
          ))}
        </select>
        <select value={sector} onChange={(e) => setFilter('sector', e.target.value)} aria-label="Sector">
          <option value="">Todos los sectores</option>
          {options?.by_sector.map((g) => (
            <option key={g.key} value={g.key}>
              {g.label}
            </option>
          ))}
        </select>
        <div className="grow" />
        <button
          className="btn btn-small"
          onClick={() =>
            downloadCsv(
              `cuadro-de-mando-${months}m.csv`,
              ['Mes', 'Nuevas', 'Importe nuevas (€)', 'Ganadas', 'Importe ganadas (€)', 'Perdidas'],
              data.monthly.map((m) => [m.month, m.new_count, m.new_eur, m.won_count, m.won_eur, m.lost_count]),
            )
          }
        >
          Descargar CSV
        </button>
      </div>

      <div className="stats">
        <Stat label="Cartera abierta" value={money(Number(k.pipeline_eur))} hint={`${k.open_count} oportunidades`} />
        <Stat label="Cartera ponderada" value={money(Number(k.weighted_pipeline_eur))} hint="Importe × probabilidad" />
        <Stat label="Ganado en el periodo" value={money(Number(k.won_eur))} hint={`${k.won_count} oportunidades`} />
        <Stat
          label="Tasa de éxito"
          value={pct(k.win_rate)}
          hint={`${k.won_count} ganadas de ${k.won_count + k.lost_count} decididas`}
        />
      </div>

      <div className="home-grid">
        <ChartCard
          title="Embudo de conversión"
          subtitle={`De las ${k.new_count} oportunidades nuevas del periodo, cuántas llegaron a cada fase`}
          table={
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Fase</th>
                  <th className="num">Llegaron</th>
                  <th className="num">%</th>
                  <th className="num">Abiertas hoy</th>
                  <th className="num">Importe abierto</th>
                </tr>
              </thead>
              <tbody>
                {data.funnel.map((f) => (
                  <tr key={f.phase}>
                    <td>{f.phase === 'F5' ? 'F5 · Ganada' : label(PHASES, f.phase)}</td>
                    <td className="num">{f.reached}</td>
                    <td className="num">{pct(f.reached_pct)}</td>
                    <td className="num">{f.phase === 'F5' ? '—' : f.open_count}</td>
                    <td className="num">{f.phase === 'F5' ? '—' : fmtMoney(f.open_eur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          }
        >
          {funnelMax ? (
            <BarList
              items={data.funnel.map((f) => ({
                key: f.phase,
                label: f.phase === 'F5' ? 'F5 · Ganada' : label(PHASES, f.phase),
                value: f.reached,
              }))}
              format={(n) => String(n)}
              detail={(phase) => {
                const f = data.funnel.find((x) => x.phase === phase)!
                return [
                  { label: 'del total', value: pct(f.reached_pct) },
                  ...(phase === 'F5' ? [] : [{ label: 'abiertas ahora', value: String(f.open_count) }]),
                ]
              }}
            />
          ) : (
            <Empty title="Sin oportunidades nuevas en el periodo" />
          )}
        </ChartCard>

        <ChartCard
          title="Evolución mensual"
          subtitle="Oportunidades nuevas, ganadas y perdidas cada mes"
          legend={TREND}
          table={
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Mes</th>
                  <th className="num">Nuevas</th>
                  <th className="num">Ganadas</th>
                  <th className="num">Importe ganado</th>
                  <th className="num">Perdidas</th>
                </tr>
              </thead>
              <tbody>
                {data.monthly.map((m) => (
                  <tr key={m.month}>
                    <td>{monthLabel(m.month)}</td>
                    <td className="num">{m.new_count}</td>
                    <td className="num">{m.won_count}</td>
                    <td className="num">{fmtMoney(m.won_eur)}</td>
                    <td className="num">{m.lost_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          }
        >
          <ColumnChart
            categories={data.monthly.map((m) => ({ key: m.month, label: monthLabel(m.month) }))}
            series={TREND}
            values={Object.fromEntries(
              data.monthly.map((m) => [m.month, { new: m.new_count, won: m.won_count, lost: m.lost_count }]),
            )}
            format={(n) => (Number.isInteger(n) ? String(n) : n.toFixed(1))}
          />
        </ChartCard>

        <ChartCard
          title="Cartera por línea de servicio"
          subtitle="Importe abierto; al pasar el ratón, la tasa de éxito del periodo"
          table={<GroupTable groups={data.by_service_line} name="Línea" />}
        >
          {data.by_service_line.length ? (
            <BarList
              items={data.by_service_line.map((g) => ({ key: g.key, label: g.label, value: Number(g.pipeline_eur) }))}
              format={moneyShort}
              detail={(key) => {
                const g = data.by_service_line.find((x) => x.key === key)!
                return [
                  { label: 'abiertas', value: String(g.open_count) },
                  { label: 'tasa de éxito', value: pct(g.win_rate) },
                ]
              }}
            />
          ) : (
            <Empty title="Sin datos" />
          )}
        </ChartCard>

        <ChartCard
          title="Cartera por sector"
          subtitle="Importe abierto por sector del cliente"
          table={<GroupTable groups={data.by_sector} name="Sector" />}
        >
          {data.by_sector.length ? (
            <BarList
              items={data.by_sector.map((g) => ({ key: g.key, label: g.label, value: Number(g.pipeline_eur) }))}
              format={moneyShort}
              detail={(key) => {
                const g = data.by_sector.find((x) => x.key === key)!
                return [
                  { label: 'abiertas', value: String(g.open_count) },
                  { label: 'tasa de éxito', value: pct(g.win_rate) },
                ]
              }}
            />
          ) : (
            <Empty title="Sin datos" />
          )}
        </ChartCard>
      </div>

      <div className="stack section-gap">
        <ChartCard
          title="Sector × línea de servicio"
          subtitle="Número de oportunidades abiertas en cada cruce: dónde se concentra la cartera"
          table={
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Sector</th>
                  <th>Línea</th>
                  <th className="num">Abiertas</th>
                  <th className="num">Importe</th>
                </tr>
              </thead>
              <tbody>
                {data.heatmap.map((c) => (
                  <tr key={`${c.sector}|${c.service_line}`}>
                    <td>{sectorName(c.sector)}</td>
                    <td>{c.service_line_label}</td>
                    <td className="num">{c.count}</td>
                    <td className="num">{fmtMoney(c.eur)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          }
        >
          {data.heatmap.length ? (
            <Heatmap
              rows={sectors.map((s) => ({ key: s, label: sectorName(s) }))}
              cols={lines.map(([key, name]) => ({ key, label: name }))}
              cell={(s, l) => {
                const c = data.heatmap.find((x) => x.sector === s && x.service_line === l)
                return c && { value: c.count, detail: fmtMoney(c.eur) }
              }}
              format={(n) => String(n)}
            />
          ) : (
            <Empty title="No hay oportunidades abiertas" />
          )}
        </ChartCard>

        <div className="home-grid">
          <section className="card">
            <h2>Clientes con más cartera</h2>
            {!data.top_clients.length && <p className="muted">Ninguna oportunidad tiene cliente asignado.</p>}
            {!!data.top_clients.length && (
              <div className="table-wrap">
              <table className="table table-compact">
                <thead>
                  <tr>
                    <th>Cliente</th>
                    <th className="num">Abiertas</th>
                    <th className="num">Cartera</th>
                    <th className="num">Ganado</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_clients.map((c) => (
                    <tr key={c.client_id}>
                      <td>{c.name ?? `Cliente ${c.client_id}`}</td>
                      <td className="num">{c.open_count}</td>
                      <td className="num">{fmtMoney(c.pipeline_eur)}</td>
                      <td className="num">{fmtMoney(c.won_eur)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </section>
          <section className="card">
            <h2>Propuestas</h2>
            <dl className="facts">
              <dt>Enviadas en el periodo</dt>
              <dd>{data.proposals.sent}</dd>
              <dt>Días de media hasta enviarla</dt>
              <dd>{data.proposals.avg_days_to_send ?? '—'}</dd>
              <dt>Rondas de revisión de media</dt>
              <dd>{data.proposals.avg_review_rounds ?? '—'}</dd>
            </dl>
            <h4>Por estado</h4>
            <div className="tags">
              {Object.entries(data.proposals.by_status).map(([s, n]) => (
                <span key={s} className="chip chip-static">
                  {label(PROPOSAL_STATUS, s)} · {n}
                </span>
              ))}
              {!Object.keys(data.proposals.by_status).length && <span className="muted">Sin propuestas.</span>}
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}

function GroupTable({ groups, name }: { groups: Overview['by_sector']; name: string }) {
  return (
    <table className="table table-compact">
      <thead>
        <tr>
          <th>{name}</th>
          <th className="num">Abiertas</th>
          <th className="num">Cartera</th>
          <th className="num">Ganadas</th>
          <th className="num">Perdidas</th>
          <th className="num">Éxito</th>
        </tr>
      </thead>
      <tbody>
        {groups.map((g) => (
          <tr key={g.key}>
            <td>{g.label}</td>
            <td className="num">{g.open_count}</td>
            <td className="num">{fmtMoney(g.pipeline_eur)}</td>
            <td className="num">{g.won}</td>
            <td className="num">{g.lost}</td>
            <td className="num">{pct(g.win_rate)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
