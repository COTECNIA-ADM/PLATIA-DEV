// Inicio del portal Low-Code: estado del motor, cifras del catálogo y acceso al editor.
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { ErrorBox, Spinner, Stat } from '../components/ui'
import { SourceNotice } from './common'
import type { AutomationStatus } from './types'

export default function Home() {
  const { can } = useAuth()
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['automation', 'status'],
    queryFn: () => api<AutomationStatus>('/api/automation/status'),
  })

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Automatizaciones</h1>
          <p className="muted">
            Lanza automatizaciones del ciclo comercial y sigue sus resultados. Las construye un grupo pequeño en n8n y
            se publican aquí cuando están revisadas.
          </p>
        </div>
        {data?.editor_url && can('automations', 'build') && (
          <a className="btn" href={data.editor_url} target="_blank" rel="noopener noreferrer">
            Abrir el editor de n8n
          </a>
        )}
      </header>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && (
        <>
          <SourceNotice source={data} />
          <div className="stats">
            <Stat label="Motor" value={data.reachable ? 'Conectado' : 'Sin conexión'} />
            <Stat label="Publicadas" value={data.published} hint="En el catálogo" />
            <Stat label="Activas" value={data.active} hint="Con su flujo encendido en n8n" />
            {data.candidates !== null && <Stat label="Flujos en n8n" value={data.candidates} hint="Con la etiqueta del catálogo" />}
          </div>
          <section className="card">
            <h2>Qué puedes hacer</h2>
            <p>
              Lanza una automatización desde el <Link to="/catalog">catálogo</Link> y sigue cómo va en{' '}
              <Link to="/runs">Ejecuciones</Link>.
              {can('automations', 'build') && (
                <>
                  {' '}
                  Prepara y envía a revisión las fichas de tus flujos en el <Link to="/workshop">Taller</Link>.
                </>
              )}
            </p>
          </section>
        </>
      )}
    </div>
  )
}
