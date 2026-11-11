// Piezas comunes del portal Low-Code.
import type { Source } from './types'

/** Aviso cuando n8n no está activado o no responde: el portal sigue funcionando. */
export function SourceNotice({ source }: { source: Source }) {
  if (source.enabled && source.reachable) return null
  return (
    <p className={`notice ${source.enabled ? 'notice-warning' : 'notice-info'}`} role="status">
      {source.problem ?? 'El motor de automatizaciones no está disponible.'}
    </p>
  )
}
