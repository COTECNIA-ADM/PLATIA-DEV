// Piezas comunes del portal Low-Code.
import { Badge, type Tone } from '../components/ui'
import type { Category, EntryStatus, FieldType, RunStatus, Source } from './types'

/** Aviso cuando n8n no está activado o no responde: el portal sigue funcionando. */
export function SourceNotice({ source }: { source: Source }) {
  if (source.enabled && source.reachable) return null
  return (
    <p className={`notice ${source.enabled ? 'notice-warning' : 'notice-info'}`} role="status">
      {source.problem ?? 'El motor de automatizaciones no está disponible.'}
    </p>
  )
}

export const RUN_STATUS: Record<RunStatus, { label: string; tone: Tone }> = {
  queued: { label: 'En cola', tone: 'neutral' },
  running: { label: 'En marcha', tone: 'info' },
  succeeded: { label: 'Terminada', tone: 'success' },
  failed: { label: 'Fallida', tone: 'danger' },
}

export const OPEN_STATUSES: RunStatus[] = ['queued', 'running']

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const s = RUN_STATUS[status] ?? { label: status, tone: 'neutral' as Tone }
  return <Badge tone={s.tone}>{s.label}</Badge>
}

/** Datos planos (entrada o resultado) como tabla de dos columnas. */
export function DataTable({ data, empty }: { data: Record<string, unknown> | null | undefined; empty: string }) {
  const entries = Object.entries(data ?? {})
  if (!entries.length) return <p className="muted">{empty}</p>
  return (
    <div className="table-wrap">
      <table className="table">
        <tbody>
          {entries.map(([key, value]) => (
            <tr key={key}>
              <th scope="row">{key}</th>
              <td>{typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value ?? '—')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export const CATEGORY: Record<Category, string> = {
  ciclo_comercial: 'Ciclo comercial',
  back_office: 'Back-office',
  plataforma: 'Plataforma',
}

export const ENTRY_STATUS: Record<EntryStatus, { label: string; tone: Tone }> = {
  draft: { label: 'Borrador', tone: 'neutral' },
  in_review: { label: 'En revisión', tone: 'warning' },
  published: { label: 'Publicada', tone: 'success' },
  retired: { label: 'Retirada', tone: 'neutral' },
}

export function EntryStatusBadge({ status }: { status: EntryStatus }) {
  const s = ENTRY_STATUS[status] ?? { label: status, tone: 'neutral' as Tone }
  return <Badge tone={s.tone}>{s.label}</Badge>
}

export const FIELD_TYPE: Record<FieldType, string> = {
  text: 'Texto',
  textarea: 'Texto largo',
  number: 'Número',
  boolean: 'Sí / no',
  date: 'Fecha',
  select: 'Lista',
}
