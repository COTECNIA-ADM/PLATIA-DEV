// Valor de la IA para el negocio: horas ahorradas y ahorro neto frente a lo que cuesta.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { fmtAiCost, fmtMoney, usdToEur } from '../lib/format'
import { ChartCard, ColumnChart, type Series } from '../components/charts'
import { Empty, ErrorBox, Spinner, Stat } from '../components/ui'
import { PeriodPicker, monthLabel, usePeriod } from './common'
import type { AIValue as AIValueData } from './types'

export const SERVICE_TYPES: Record<string, string> = {
  document_analysis: 'Análisis de documentos',
  document_enrichment: 'Resumen de documentos',
  opportunity_scoring: 'Puntuación de oportunidades',
  opportunity_analysis: 'Análisis GO/NO-GO',
  proposal_generation: 'Redacción de propuestas',
  chat_rag: 'Preguntas a los documentos',
  rag_query_rewrite: 'Reformular preguntas',
  rag_evaluation: 'Evaluar respuestas',
  intent_classification: 'Clasificar búsquedas',
  agent_copilot: 'Copiloto',
  chat_summary: 'Resumir conversaciones',
  memory_extraction: 'Memoria del copiloto',
  cv_tailoring: 'CV a medida',
  proposal_deck: 'Presentación de la propuesta',
  analytics_qa: 'Preguntas sobre los datos',
}

const COST: Series[] = [{ key: 'cost', label: 'Gasto (€)', color: 'var(--series-1)' }]
const eurFmt = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 })

export default function AIValue() {
  const [months, setMonths] = usePeriod()
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['analytics', 'ai', months],
    queryFn: () => api<AIValueData>('/api/analytics/ai', { query: { months } }),
    placeholderData: keepPreviousData,
  })
  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!data) return null
  const t = data.roi.total
  return (
    <div className={`page${isFetching ? ' is-refreshing' : ''}`}>
      <header className="page-head">
        <div>
          <h1>Valor de la IA</h1>
          <p className="muted">
            Tiempo que la IA ahorra al equipo, comparado con el que costaría hacerlo a mano, y lo que cuesta.
          </p>
        </div>
      </header>
      <div className="toolbar">
        <PeriodPicker months={months} onChange={setMonths} />
      </div>
      <div className="stats">
        <Stat label="Tareas hechas con IA" value={t.tasks.toLocaleString('es-ES')} />
        <Stat label="Horas ahorradas" value={t.hours_saved.toLocaleString('es-ES')} />
        <Stat label="Ahorro neto" value={fmtMoney(t.net_saving_eur)} hint="Ya descontado el coste de la IA" />
        <Stat label="Coste de la IA" value={eurFmt.format(Number(t.cost_eur))} hint="En euros, al cambio configurado" />
      </div>
      <div className="home-grid">
        <section className="card">
          <h2>Por tipo de tarea</h2>
          {!data.roi.services.length ? (
            <Empty title="Sin tareas con IA en el periodo" />
          ) : (
            <div className="table-wrap">
              <table className="table table-compact">
                <thead>
                  <tr>
                    <th>Tarea</th>
                    <th className="num">Veces</th>
                    <th className="num">Horas ahorradas</th>
                    <th className="num">Ahorro neto</th>
                    <th className="num">Coste</th>
                    <th className="num">Valoración</th>
                  </tr>
                </thead>
                <tbody>
                  {data.roi.services.map((s) => (
                    <tr key={s.service_type}>
                      <td>{SERVICE_TYPES[s.service_type] ?? s.service_type}</td>
                      <td className="num">{s.tasks}</td>
                      <td className="num">{s.hours_saved.toLocaleString('es-ES')}</td>
                      <td className="num">{fmtMoney(s.net_saving_eur)}</td>
                      <td className="num">{eurFmt.format(Number(s.cost_eur))}</td>
                      <td className="num">{s.avg_user_rating ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted field-hint">
            El ahorro se calcula con el tiempo que lleva cada tarea a mano y el coste por hora que fija
            Administración.
          </p>
        </section>
        <ChartCard
          title="Gasto en IA por mes"
          subtitle="Todas las llamadas a modelos, en euros al cambio configurado"
          table={
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Mes</th>
                  <th className="num">Llamadas</th>
                  <th className="num">Gasto</th>
                </tr>
              </thead>
              <tbody>
                {data.monthly.map((m) => (
                  <tr key={m.month}>
                    <td>{monthLabel(m.month)}</td>
                    <td className="num">{m.calls}</td>
                    <td className="num">{fmtAiCost(m.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          }
        >
          <ColumnChart
            categories={data.monthly.map((m) => ({ key: m.month, label: monthLabel(m.month) }))}
            series={COST}
            values={Object.fromEntries(data.monthly.map((m) => [m.month, { cost: usdToEur(Number(m.cost_usd)) }]))}
            format={(n) => eurFmt.format(n)}
          />
        </ChartCard>
      </div>
    </div>
  )
}
