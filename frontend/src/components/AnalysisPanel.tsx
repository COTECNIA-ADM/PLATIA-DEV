// Análisis GO/NO-GO de un documento o una oportunidad (Capítulo 11).
// Se lanza en segundo plano (202) y se consulta cada pocos segundos hasta que termina.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../lib/api'
import { MEETS, SEVERITY, fmtDateTime, label } from '../lib/format'
import type { Analysis } from '../lib/types'
import { Verdict } from './status'
import { Badge, ErrorBox, ScoreBar, Spinner, errorMessage, useToast } from './ui'

const SCORE_LABELS: Record<string, string> = {
  technical_capability: 'Capacidad técnica',
  strategic_fit: 'Encaje estratégico',
  economic_viability: 'Viabilidad económica',
  competition: 'Competencia',
  risk: 'Riesgo',
}

const MEETS_TONE = { yes: 'success', partial: 'warning', no: 'danger', unknown: 'neutral' } as const

function List({ title, items }: { title: string; items: string[] | undefined }) {
  if (!items?.length) return null
  return (
    <div>
      <h4>{title}</h4>
      <ul>
        {items.map((x, i) => (
          <li key={i}>{x}</li>
        ))}
      </ul>
    </div>
  )
}

export function AnalysisResult({ analysis }: { analysis: Analysis }) {
  const r = analysis.result
  if (!r) return null
  return (
    <div className="analysis">
      <div className="analysis-head">
        <Verdict verdict={analysis.verdict} />
        {analysis.confidence !== null && <span className="muted">Confianza {Math.round(analysis.confidence * 100)} %</span>}
        <span className="muted">
          {analysis.model} · {fmtDateTime(analysis.completed_at)}
        </span>
      </div>
      {r.summary && <p className="lead">{r.summary}</p>}
      {analysis.truncated && (
        <p className="notice notice-warning">El documento era muy largo y se analizó una parte. Revisa el original.</p>
      )}
      {r.scores && (
        <div className="scores">
          {Object.entries(r.scores).map(([k, v]) => (
            <div key={k} className="score-row">
              <span>{SCORE_LABELS[k] ?? k}</span>
              <ScoreBar value={v} />
            </div>
          ))}
        </div>
      )}
      {!!r.requirements?.length && (
        <div>
          <h4>Requisitos</h4>
          <table className="table table-compact">
            <tbody>
              {r.requirements.map((q, i) => (
                <tr key={i}>
                  <td>
                    {q.requirement}
                    {q.evidence && <div className="row-sub">{q.evidence}</div>}
                  </td>
                  <td>{q.kind === 'mandatory' ? <Badge>Obligatorio</Badge> : <Badge tone="info">Valorable</Badge>}</td>
                  <td>
                    <Badge tone={MEETS_TONE[q.meets as keyof typeof MEETS_TONE] ?? 'neutral'}>{label(MEETS, q.meets)}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!!r.risks?.length && (
        <div>
          <h4>Riesgos</h4>
          <ul>
            {r.risks.map((x, i) => (
              <li key={i}>
                <Badge tone={x.severity === 'high' ? 'danger' : x.severity === 'medium' ? 'warning' : 'neutral'}>
                  {label(SEVERITY, x.severity)}
                </Badge>{' '}
                {x.description}
                {x.mitigation && <div className="row-sub">Mitigación: {x.mitigation}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="grid-2">
        <List title="Condiciones" items={r.conditions} />
        <List title="Próximos pasos" items={r.next_steps} />
      </div>
      <List title="Falta información sobre" items={r.missing_information} />
    </div>
  )
}

/**
 * @param path ruta del recurso, p. ej. /api/documents/5 (se le añade /analysis)
 * @param canRun si la persona puede lanzar un análisis nuevo
 */
export default function AnalysisPanel({ path, canRun, disabledReason }: { path: string; canRun: boolean; disabledReason?: string }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const key = ['analysis', path]
  const { data, error, isLoading } = useQuery({
    queryKey: key,
    queryFn: async () => {
      try {
        return await api<Analysis>(`${path}/analysis`)
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null
        throw err
      }
    },
    // Mientras está en cola o en marcha, se vuelve a preguntar cada 3 segundos
    refetchInterval: (query) => {
      const a = query.state.data
      return a && (a.status === 'queued' || a.status === 'running') ? 3000 : false
    },
  })

  const run = useMutation({
    mutationFn: () => api<Analysis>(`${path}/analysis`, { method: 'POST' }),
    onSuccess: (a) => {
      queryClient.setQueryData(key, a)
      toast('Análisis en marcha. Suele tardar menos de un minuto.')
    },
    onError: (err) => toast(errorMessage(err), 'danger'),
  })

  const running = data && (data.status === 'queued' || data.status === 'running')
  return (
    <section className="card">
      <header className="card-head">
        <h2>Análisis GO/NO-GO</h2>
        {canRun && (
          <button className="btn" onClick={() => run.mutate()} disabled={run.isPending || !!running || !!disabledReason} title={disabledReason}>
            {data ? 'Analizar de nuevo' : 'Analizar con IA'}
          </button>
        )}
      </header>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} />}
      {!isLoading && !data && !error && (
        <p className="muted">
          {disabledReason ?? 'Todavía no hay análisis. La IA revisa requisitos, riesgos y encaje, y propone si presentarse.'}
        </p>
      )}
      {running && <Spinner label="Analizando… puedes seguir trabajando, te avisaremos al terminar." />}
      {data?.status === 'failed' && <p className="notice notice-error">El análisis falló: {data.error ?? 'error desconocido'}</p>}
      {data?.status === 'done' && <AnalysisResult analysis={data} />}
    </section>
  )
}
