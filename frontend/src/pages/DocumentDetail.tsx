import { useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, download } from '../lib/api'
import { useAuth } from '../lib/auth'
import { DOC_LINK_ROLES, fmtBytes, fmtDateTime, label } from '../lib/format'
import type { DocumentDetail as Doc } from '../lib/types'
import AnalysisPanel from '../components/AnalysisPanel'
import AskDocuments from '../components/AskDocuments'
import { DocumentStatus, IndexStatus } from '../components/status'
import { Badge, ErrorBox, Field, Modal, Spinner, errorMessage, useToast } from '../components/ui'
import { ACCEPT, DOC_TYPES } from './Documents'

const OPERATIONS_ROLES: Record<string, string> = { manager: 'Responsable comercial', analyst: 'Analista', viewer: 'Consulta' }

const ENTITY_LABELS: Record<string, string> = {
  organizations: 'Organizaciones',
  amounts: 'Importes',
  dates: 'Fechas y plazos',
  requirements: 'Requisitos',
}

function Access({ doc, onSaved, onClose }: { doc: Doc; onSaved: (d: Doc) => void; onClose: () => void }) {
  const [roles, setRoles] = useState<string[]>(doc.allowed_roles ?? [])
  const save = useMutation({
    mutationFn: () => api<Doc>(`/api/documents/${doc.id}`, { method: 'PATCH', body: { version: doc.version, allowed_roles: roles } }),
    onSuccess: onSaved,
  })
  return (
    <Modal title="Quién puede ver este documento" onClose={onClose}>
      <div className="stack">
        <p className="muted">
          Sin marcar ninguno, lo ve cualquiera con acceso a documentos. Si marcas roles, solo lo ven esos roles, quien lo subió y los
          gestores. Para los demás no existe: tampoco aparece en búsquedas ni en las respuestas de la IA.
        </p>
        {Object.entries(OPERATIONS_ROLES).map(([k, v]) => (
          <label key={k} className="check">
            <input
              type="checkbox"
              checked={roles.includes(k)}
              onChange={() => setRoles(roles.includes(k) ? roles.filter((r) => r !== k) : [...roles, k])}
            />
            <span>{v}</span>
          </label>
        ))}
        {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
        <div className="actions">
          <button className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
            Guardar
          </button>
        </div>
      </div>
    </Modal>
  )
}

function Rename({ doc, onSaved, onClose }: { doc: Doc; onSaved: (d: Doc) => void; onClose: () => void }) {
  const [title, setTitle] = useState(doc.title)
  const [docType, setDocType] = useState(doc.doc_type ?? '')
  const save = useMutation({
    mutationFn: () =>
      api<Doc>(`/api/documents/${doc.id}`, { method: 'PATCH', body: { version: doc.version, title, doc_type: docType || null } }),
    onSuccess: onSaved,
  })
  return (
    <Modal title="Editar documento" onClose={onClose}>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Field label="Título">
          <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={500} />
        </Field>
        <Field label="Tipo">
          <select value={docType} onChange={(e) => setDocType(e.target.value)}>
            <option value="">—</option>
            {Object.entries(DOC_TYPES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </Field>
        {save.error && (
          <p className="notice notice-error">
            {save.error instanceof ApiError && save.error.status === 409 ? 'Alguien lo ha cambiado. Recarga e inténtalo de nuevo.' : errorMessage(save.error)}
          </p>
        )}
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

export default function DocumentDetail() {
  const id = Number(useParams().id)
  const navigate = useNavigate()
  const toast = useToast()
  const { can, canModify, hasAI } = useAuth()
  const queryClient = useQueryClient()
  const versionInput = useRef<HTMLInputElement>(null)
  const [dialog, setDialog] = useState<'access' | 'rename' | null>(null)
  const key = ['documents', id]
  const { data: doc, error, isLoading, refetch } = useQuery({
    queryKey: key,
    queryFn: () => api<Doc>(`/api/documents/${id}`),
    refetchInterval: (query) => {
      const d = query.state.data
      if (!d) return false
      const recent = Date.now() - new Date(d.created_at).getTime() < 10 * 60_000
      const busy = d.processing_status === 'pending' || d.processing_status === 'processing' || d.index_status === 'pending'
      // El resumen de la IA llega poco después de procesarlo; si no llega en 10 minutos, se deja de esperar
      return busy || (recent && !d.ai_enriched_at && d.processing_status === 'processed') ? 4000 : false
    },
  })

  const saved = (d: Doc) => {
    queryClient.setQueryData(key, d)
    void queryClient.invalidateQueries({ queryKey: ['documents', 'list'] })
    setDialog(null)
    toast('Cambios guardados')
  }
  const reprocess = useMutation({
    mutationFn: () => api(`/api/documents/${id}/reprocess`, { method: 'POST' }),
    onSuccess: () => {
      toast('Se está procesando de nuevo')
      void refetch()
    },
    onError: (err) => toast(errorMessage(err), 'danger'),
  })
  const remove = useMutation({
    mutationFn: () => api(`/api/documents/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      toast('Documento borrado')
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
      navigate('/documents')
    },
    onError: (err) => toast(errorMessage(err), 'danger'),
  })
  const newVersion = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api<Doc>(`/api/documents/${id}/versions`, { form })
    },
    onSuccess: (d) => {
      toast(`Versión ${d.version_number} subida`)
      navigate(`/documents/${d.id}`)
    },
    onError: (err) => toast(errorMessage(err), 'danger'),
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!doc) return null

  const writable = can('documents', 'write') && canModify('documents', doc.created_by)
  const processed = doc.processing_status === 'processed'
  const entities = Object.entries(ENTITY_LABELS).filter(([k]) => Array.isArray(doc.ai_entities?.[k]) && (doc.ai_entities?.[k] as unknown[]).length)

  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/documents">Documentos</Link> / #{doc.id}
      </nav>
      <header className="page-head">
        <div>
          <h1>{doc.title}</h1>
          <div className="meta-row">
            <DocumentStatus status={doc.processing_status} />
            <IndexStatus status={doc.index_status} />
            {doc.is_restricted && <Badge tone="warning">Restringido</Badge>}
            {!doc.is_current_version && <Badge tone="warning">Versión antigua</Badge>}
            <span className="muted">
              {doc.original_filename} · {fmtBytes(doc.file_size_bytes)} · v{doc.version_number}
            </span>
          </div>
        </div>
        <div className="btn-row">
          <button className="btn" onClick={() => void download(`/api/documents/${id}/download`, doc.original_filename ?? 'documento').catch((e) => toast(errorMessage(e), 'danger'))}>
            Descargar
          </button>
          {writable && doc.is_current_version && (
            <>
              <button className="btn" onClick={() => setDialog('rename')}>
                Editar
              </button>
              <button className="btn" onClick={() => setDialog('access')}>
                Acceso
              </button>
              <button className="btn" onClick={() => versionInput.current?.click()} disabled={newVersion.isPending}>
                Subir versión nueva
              </button>
              <input
                ref={versionInput}
                type="file"
                hidden
                accept={ACCEPT}
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) newVersion.mutate(file)
                  e.target.value = ''
                }}
              />
            </>
          )}
        </div>
      </header>

      {doc.processing_status === 'failed' && (
        <div className="notice notice-error">
          <span>No se pudo leer el documento: {doc.processing_error ?? 'error desconocido'}</span>
          {writable && (
            <button className="btn btn-small" onClick={() => reprocess.mutate()}>
              Reintentar
            </button>
          )}
        </div>
      )}
      {(doc.processing_status === 'pending' || doc.processing_status === 'processing') && (
        <Spinner label="Extrayendo el texto… la página se actualiza sola." />
      )}

      <div className="detail-grid">
        <div className="stack">
          {processed && hasAI('document_analyzer') && (
            <section className="card">
              <h2>Pregunta sobre este documento</h2>
              {doc.index_status === 'indexed' ? (
                <AskDocuments documentIds={[doc.id]} />
              ) : (
                <p className="muted">Disponible en cuanto termine de indexarse.</p>
              )}
            </section>
          )}
          <AnalysisPanel
            path={`/api/documents/${id}`}
            canRun={hasAI('document_analyzer')}
            disabledReason={processed ? undefined : 'Se podrá analizar cuando termine de procesarse.'}
          />
          {doc.text_preview && (
            <section className="card">
              <h2>Texto extraído</h2>
              <p className="muted">{doc.text_length?.toLocaleString('es-ES')} caracteres. Primeras líneas:</p>
              <pre className="text-preview">{doc.text_preview}</pre>
            </section>
          )}
        </div>
        <aside className="stack">
          <section className="card">
            <h2>Resumen de la IA</h2>
            {doc.ai_summary ? <p>{doc.ai_summary}</p> : <p className="muted">{processed ? 'Generándolo…' : 'Aún no disponible.'}</p>}
            {!!doc.ai_keywords?.length && (
              <div className="tags">
                {doc.ai_keywords.map((k) => (
                  <Badge key={k}>{k}</Badge>
                ))}
              </div>
            )}
            {entities.map(([k, v]) => (
              <div key={k}>
                <h4>{v}</h4>
                <ul className="compact-list">
                  {(doc.ai_entities?.[k] as string[]).slice(0, 8).map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
            ))}
          </section>
          <section className="card">
            <dl className="facts">
              <dt>Tipo</dt>
              <dd>{DOC_TYPES[doc.doc_type ?? ''] ?? doc.doc_type ?? '—'}</dd>
              <dt>Subido</dt>
              <dd>{fmtDateTime(doc.created_at)}</dd>
              <dt>Procesado</dt>
              <dd>{fmtDateTime(doc.processed_at)}</dd>
              <dt>Fragmentos indexados</dt>
              <dd>{doc.vector_count ?? '—'}</dd>
              <dt>Acceso</dt>
              <dd>{doc.allowed_roles?.length ? doc.allowed_roles.map((r) => OPERATIONS_ROLES[r] ?? r).join(', ') : 'Todos'}</dd>
            </dl>
          </section>
          {!!doc.opportunities.length && (
            <section className="card">
              <h2>Oportunidades</h2>
              <ul className="plain-list">
                {doc.opportunities.map((o) => (
                  <li key={o.opportunity_id}>
                    <Link to={`/opportunities/${o.opportunity_id}`}>Oportunidad #{o.opportunity_id}</Link>{' '}
                    <span className="muted">{label(DOC_LINK_ROLES, o.role)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {doc.versions && doc.versions.length > 1 && (
            <section className="card">
              <h2>Versiones</h2>
              <ul className="plain-list">
                {doc.versions
                  .slice()
                  .reverse()
                  .map((v) => (
                    <li key={v.id}>
                      {v.id === doc.id ? <strong>v{v.version_number}</strong> : <Link to={`/documents/${v.id}`}>v{v.version_number}</Link>}{' '}
                      <span className="muted">{fmtDateTime(v.created_at)}</span> {v.is_current_version && <Badge tone="success">actual</Badge>}
                    </li>
                  ))}
              </ul>
            </section>
          )}
          {writable && doc.is_current_version && can('documents', 'delete') && (
            <button
              className="btn btn-danger-ghost"
              onClick={() => {
                if (window.confirm('¿Borrar el documento y todas sus versiones? Se puede recuperar desde administración.')) remove.mutate()
              }}
            >
              Borrar documento
            </button>
          )}
        </aside>
      </div>
      {dialog === 'access' && <Access doc={doc} onSaved={saved} onClose={() => setDialog(null)} />}
      {dialog === 'rename' && <Rename doc={doc} onSaved={saved} onClose={() => setDialog(null)} />}
    </div>
  )
}
