// Cuadro de mando de negocio: cartera, embudo, tendencia, líneas de servicio y sectores.
// Fase 9a: variación frente al periodo anterior, evolución de la cartera, objetivos y
// «Pregunta a tus datos».
import { useState, type FormEvent } from 'react'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { PHASES, PROPOSAL_STATUS, SECTORS, fmtDate, fmtMoney, label } from '../lib/format'
import { BarList, ChartCard, ColumnChart, Heatmap, compact, type Series } from '../components/charts'
import { Markdown } from '../components/text'
import { AiNote, Badge, Empty, ErrorBox, Spinner, Stat, errorMessage } from '../components/ui'
import { Delta, PeriodPicker, TARGET_METRICS, downloadCsv, fmtMetric, monthLabel, pct, usePeriod } from './common'
import type { AskAnswer, Overview } from './types'

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
const PIPELINE: Series[] = [
  { key: 'pipeline', label: 'Cartera abierta', color: 'var(--series-1)' },
  { key: 'weighted', label: 'Ponderada', color: 'var(--series-2)' },
]
const num = (v: string | number | null | undefined) => (v === null || v === undefined ? null : Number(v))

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
  const p = data.previous
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
        <Stat
          label="Cartera abierta"
          value={money(Number(k.pipeline_eur))}
          hint={
            <>
              <Delta now={num(k.pipeline_eur)} before={num(p.pipeline_eur)} />
              {k.open_count} oportunidades
            </>
          }
        />
        <Stat
          label="Oportunidades nuevas"
          value={k.new_count}
          hint={
            <>
              <Delta now={k.new_count} before={p.new_count} />
              antes {p.new_count}
            </>
          }
        />
        <Stat
          label="Ganado en el periodo"
          value={money(Number(k.won_eur))}
          hint={
            <>
              <Delta now={num(k.won_eur)} before={num(p.won_eur)} />
              {k.won_count} oportunidades
            </>
          }
        />
        <Stat
          label="Tasa de éxito"
          value={pct(k.win_rate)}
          hint={
            <>
              <Delta now={k.win_rate} before={p.win_rate} kind="points" />
              {k.won_count} de {k.won_count + k.lost_count} decididas
            </>
          }
        />
      </div>
      <p className="muted small">
        Variación frente a los {months} meses anteriores ({fmtDate(p.from)} – {fmtDate(p.to)})
        {p.pipeline_date ? `; la cartera, frente a la foto del ${fmtDate(p.pipeline_date)}` : ''}.
      </p>

      {/* Las fotos de cartera guardan el total y los objetivos son por línea: con filtro de
          sector no hay comparación posible */}
      {!sector && (
        <div className="home-grid section-gap">
          <TargetsCard targets={data.targets} />
          {!line && <PipelineCard history={data.pipeline_history} />}
        </div>
      )}

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
        <AskPanel months={months} line={line} sector={sector} />
      </div>
    </div>
  )
}

function TargetsCard({ targets }: { targets: Overview['targets'] }) {
  return (
    <section className="card">
      <header className="card-head">
        <h2>Objetivos</h2>
        <Link to="/targets" className="btn btn-small btn-ghost">
          Gestionar
        </Link>
      </header>
      {!targets.length ? (
        <Empty title="Sin objetivos en este periodo">Defínelos en la página de objetivos o impórtalos desde Excel.</Empty>
      ) : (
        <ul className="targets-list">
          {targets.map((t) => {
            const progress = t.progress ?? 0
            return (
              <li key={t.metric}>
                <div className="targets-row">
                  <strong>{TARGET_METRICS[t.metric]}</strong>
                  <span>
                    {fmtMetric(t.metric, t.actual)} de {fmtMetric(t.metric, t.target)} · {pct(t.progress)}
                  </span>
                </div>
                <span
                  className={`progress${progress >= 1 ? ' progress-done' : ''}`}
                  role="meter"
                  aria-label={TARGET_METRICS[t.metric]}
                  aria-valuenow={Math.round(progress * 100)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <span className="progress-fill" style={{ width: `${Math.min(1, progress) * 100}%` }} />
                </span>
                <span className="muted small">
                  {t.months.length === 1 ? monthLabel(t.months[0]) : `${monthLabel(t.months[0])} – ${monthLabel(t.months[t.months.length - 1])}`}
                  {' '}({t.months.length} {t.months.length === 1 ? 'mes' : 'meses'} con objetivo)
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function PipelineCard({ history }: { history: Overview['pipeline_history'] }) {
  return (
    <ChartCard
      title="Evolución de la cartera"
      subtitle="Cartera abierta al cierre de cada semana (foto nocturna)"
      legend={PIPELINE}
      table={
        <table className="table table-compact">
          <thead>
            <tr>
              <th>Semana</th>
              <th className="num">Abiertas</th>
              <th className="num">Cartera</th>
              <th className="num">Ponderada</th>
            </tr>
          </thead>
          <tbody>
            {history.map((h) => (
              <tr key={h.date}>
                <td>{fmtDate(h.date)}</td>
                <td className="num">{h.open_count}</td>
                <td className="num">{fmtMoney(h.pipeline_eur)}</td>
                <td className="num">{fmtMoney(h.weighted_pipeline_eur)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      }
    >
      {history.length < 2 ? (
        <Empty title="Aún hay pocas fotos">La cartera se guarda cada noche; la evolución aparece a partir de la segunda semana.</Empty>
      ) : (
        <ColumnChart
          categories={history.map((h) => ({ key: h.date, label: fmtDate(h.date).slice(0, 5) }))}
          series={PIPELINE}
          values={Object.fromEntries(
            history.map((h) => [h.date, { pipeline: Number(h.pipeline_eur), weighted: Number(h.weighted_pipeline_eur) }]),
          )}
          format={moneyShort}
        />
      )}
    </ChartCard>
  )
}

const EXAMPLES = [
  '¿Qué línea de servicio ha crecido más frente al periodo anterior?',
  '¿En qué sector deberíamos centrar el esfuerzo comercial?',
  '¿Vamos a cumplir los objetivos de este año?',
]

function AskPanel({ months, line, sector }: { months: number; line: string; sector: string }) {
  const { hasAI } = useAuth()
  const [question, setQuestion] = useState('')
  const ask = useMutation({
    mutationFn: (q: string) =>
      api<AskAnswer>('/api/analytics/ask', {
        body: { question: q, months, service_line: line || null, sector: sector || null },
      }),
  })
  if (!hasAI('analytics_assistant')) return null
  function submit(e: FormEvent) {
    e.preventDefault()
    if (question.trim()) ask.mutate(question.trim())
  }
  return (
    <section className="card ask-box">
      <h2>Pregunta a tus datos</h2>
      <p className="muted">
        La IA responde solo con las cifras de este cuadro de mando (con los filtros elegidos), el mapa de oportunidad y
        los competidores. No ve datos personales.
      </p>
      <form className="stack" onSubmit={submit}>
        <textarea
          rows={2}
          maxLength={2000}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={EXAMPLES[0]}
          aria-label="Pregunta"
        />
        <div className="btn-row">
          {EXAMPLES.map((q) => (
            <button key={q} type="button" className="chip" onClick={() => setQuestion(q)}>
              {q}
            </button>
          ))}
          <div className="grow" />
          <button className="btn btn-primary" disabled={ask.isPending || !question.trim()}>
            {ask.isPending ? 'Pensando…' : 'Preguntar'}
          </button>
        </div>
      </form>
      {ask.error && <p className="notice notice-error">{errorMessage(ask.error)}</p>}
      {ask.data && (
        <div className="stack section-gap">
          {!ask.data.sufficient_data && <Badge tone="warning">Datos insuficientes para una respuesta firme</Badge>}
          <Markdown text={ask.data.answer} />
          <AiNote />
        </div>
      )}
    </section>
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
