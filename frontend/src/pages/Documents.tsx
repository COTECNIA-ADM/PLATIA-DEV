// Documentos: subida (varios a la vez, con arrastrar y soltar) y listado con su estado
// de procesamiento. Mientras haya alguno pendiente, la lista se refresca sola.
import { useRef, useState, type DragEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { DOC_STATUS, fmtBytes, fmtRelative } from '../lib/format'
import type { DocumentDetail, DocumentSummary, Page } from '../lib/types'
import { DocumentStatus, IndexStatus } from '../components/status'
import { Badge, Empty, ErrorBox, Pager, Spinner, useDebounced } from '../components/ui'

export const ACCEPT = '.pdf,.docx,.doc,.odt,.rtf,.txt,.md,.csv,.xlsx,.pptx'
export const DOC_TYPES: Record<string, string> = {
  pliego: 'Pliego',
  anexo: 'Anexo',
  propuesta: 'Propuesta anterior',
  cv: 'CV',
  contrato: 'Contrato',
  otro: 'Otro',
}

type UploadResult = { name: string; ok: boolean; message: string; id?: number }

function Uploader({ onUploaded }: { onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [docType, setDocType] = useState('pliego')
  const [over, setOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<UploadResult[]>([])

  async function upload(files: FileList | File[]) {
    setBusy(true)
    const out: UploadResult[] = []
    for (const file of Array.from(files)) {
      const form = new FormData()
      form.append('file', file)
      form.append('doc_type', docType)
      try {
        const doc = await api<DocumentDetail>('/api/documents', { form })
        out.push({ name: file.name, ok: true, message: 'Subido. Se está procesando.', id: doc.id })
      } catch (err) {
        const existing = err instanceof ApiError ? (err.body.existing_document_id as number | undefined) : undefined
        out.push({ name: file.name, ok: false, message: (err as Error).message, id: existing })
      }
      setResults([...out])
    }
    setBusy(false)
    onUploaded()
  }

  function drop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    if (e.dataTransfer.files.length) void upload(e.dataTransfer.files)
  }

  return (
    <section className="card">
      <div
        className={`dropzone${over ? ' dropzone-over' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
      >
        <p>
          <strong>Arrastra aquí los ficheros</strong> o{' '}
          <button className="btn-link" onClick={() => input.current?.click()} disabled={busy}>
            elígelos
          </button>
        </p>
        <p className="muted">PDF, Word, ODT, RTF, TXT, Markdown, CSV, Excel o PowerPoint.</p>
        <label className="inline-field">
          Tipo:
          <select value={docType} onChange={(e) => setDocType(e.target.value)}>
            {Object.entries(DOC_TYPES).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
        </label>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          onChange={(e) => {
            if (e.target.files?.length) void upload(e.target.files)
            e.target.value = ''
          }}
        />
        {busy && <Spinner label="Subiendo…" />}
      </div>
      {results.length > 0 && (
        <ul className="plain-list upload-results">
          {results.map((r, i) => (
            <li key={i} className={r.ok ? 'text-success' : 'text-danger'}>
              {r.name}: {r.message}{' '}
              {r.id && <Link to={`/documents/${r.id}`}>{r.ok ? 'Abrir' : 'Ver el que ya existe'}</Link>}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export default function Documents() {
  const { can } = useAuth()
  const queryClient = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const q = useDebounced(text.trim(), 300)
  const filters = {
    q,
    doc_type: params.get('type') ?? '',
    processing_status: params.get('status') ?? '',
    mine: params.get('mine') === 'true' ? 'true' : '',
    page: Number(params.get('page') ?? 1),
  }
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['documents', 'list', filters],
    queryFn: () => api<Page<DocumentSummary>>('/api/documents', { query: filters }),
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      query.state.data?.items.some((d) => d.processing_status === 'pending' || d.processing_status === 'processing' || d.index_status === 'pending')
        ? 4000
        : false,
  })

  function update(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (!v) next.delete(k)
      else next.set(k, v)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next, { replace: true })
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Documentos</h1>
          <p className="muted">Pliegos, anexos y propuestas anteriores. La IA los lee, resume e indexa al subirlos.</p>
        </div>
      </header>
      {can('documents', 'upload') && <Uploader onUploaded={() => void queryClient.invalidateQueries({ queryKey: ['documents'] })} />}

      <div className="toolbar">
        <input
          type="search"
          className="grow"
          placeholder="Buscar por título o nombre de fichero"
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            update({ q: e.target.value.trim() || null })
          }}
        />
        <select value={filters.doc_type} onChange={(e) => update({ type: e.target.value })} aria-label="Tipo">
          <option value="">Todos los tipos</option>
          {Object.entries(DOC_TYPES).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select value={filters.processing_status} onChange={(e) => update({ status: e.target.value })} aria-label="Estado">
          <option value="">Todos los estados</option>
          {Object.entries(DOC_STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <button className={`chip${filters.mine ? ' chip-on' : ''}`} onClick={() => update({ mine: filters.mine ? null : 'true' })}>
          Subidos por mí
        </button>
      </div>

      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="No hay documentos">Sube el primero arrastrándolo a la zona de arriba.</Empty>}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Documento</th>
                <th>Tipo</th>
                <th>Estado</th>
                <th>Búsqueda IA</th>
                <th className="num">Tamaño</th>
                <th>Subido</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((d) => (
                <tr key={d.id}>
                  <td>
                    <Link to={`/documents/${d.id}`} className="row-title">
                      {d.title}
                    </Link>{' '}
                    {d.version_number > 1 && <Badge>v{d.version_number}</Badge>} {d.is_restricted && <Badge tone="warning">Restringido</Badge>}
                    {d.ai_summary && <div className="row-snippet">{d.ai_summary}</div>}
                  </td>
                  <td>{DOC_TYPES[d.doc_type ?? ''] ?? d.doc_type ?? '—'}</td>
                  <td>
                    <DocumentStatus status={d.processing_status} />
                  </td>
                  <td>
                    <IndexStatus status={d.index_status} />
                  </td>
                  <td className="num">{fmtBytes(d.file_size_bytes)}</td>
                  <td>{fmtRelative(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pager pagination={data.pagination} onPage={(p) => update({ page: String(p) })} />}
    </div>
  )
}
