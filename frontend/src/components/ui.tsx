// Piezas comunes de la interfaz: estados de carga y error, insignias, paginación,
// diálogos y avisos. Sin dependencias externas.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { ApiError } from '../lib/api'
import type { Pagination } from '../lib/types'

/** Marca del contenido generado con IA (fase 8): siempre visible junto a la respuesta. */
export function AiNote({ children = 'Generado con IA · revísalo antes de usarlo' }: { children?: ReactNode }) {
  return (
    <p className="ai-note">
      <span aria-hidden="true">✦</span> {children}
    </p>
  )
}

export function Spinner({ label = 'Cargando…' }: { label?: string }) {
  return (
    <div className="spinner" role="status">
      <span className="spinner-dot" aria-hidden />
      {label}
    </div>
  )
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return 'Ha fallado algo inesperado.'
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="notice notice-error" role="alert">
      <span>{errorMessage(error)}</span>
      {onRetry && (
        <button className="btn btn-small" onClick={onRetry}>
          Reintentar
        </button>
      )}
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children && <div>{children}</div>}
    </div>
  )
}

export type Tone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'accent'

export function Badge({ tone = 'neutral', children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  )
}

export function Pager({ pagination, onPage }: { pagination: Pagination; onPage: (page: number) => void }) {
  if (pagination.pages <= 1) return null
  return (
    <nav className="pager" aria-label="Paginación">
      <button className="btn btn-small" disabled={pagination.page <= 1} onClick={() => onPage(pagination.page - 1)}>
        Anterior
      </button>
      <span>
        Página {pagination.page} de {pagination.pages} · {pagination.total} en total
      </span>
      <button
        className="btn btn-small"
        disabled={pagination.page >= pagination.pages}
        onClick={() => onPage(pagination.page + 1)}
      >
        Siguiente
      </button>
    </nav>
  )
}

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    dialog?.showModal()
    return () => dialog?.close()
  }, [])
  return (
    <dialog
      ref={ref}
      className={`modal${wide ? ' modal-wide' : ''}`}
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
    >
      <header className="modal-head">
        <h2>{title}</h2>
        <button className="btn-icon" onClick={onClose} aria-label="Cerrar">
          ×
        </button>
      </header>
      <div className="modal-body">{children}</div>
    </dialog>
  )
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </label>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  )
}

/** Puntuación de 0 a 10 como barra. */
export function ScoreBar({ value, max = 10 }: { value: number | null | undefined; max?: number }) {
  if (value === null || value === undefined) return <span className="muted">—</span>
  const pct = Math.max(0, Math.min(100, (value / max) * 100))
  const tone = pct >= 70 ? 'success' : pct >= 40 ? 'warning' : 'danger'
  return (
    <span className="scorebar" title={`${value.toFixed(1)} de ${max}`}>
      <span className={`scorebar-fill scorebar-${tone}`} style={{ width: `${pct}%` }} />
      <span className="scorebar-text">{value.toLocaleString('es-ES', { maximumFractionDigits: 1 })}</span>
    </span>
  )
}

// ---------------------------------------------------------------- Avisos (toasts)
type Toast = { id: number; text: string; tone: Tone }
const ToastContext = createContext<(text: string, tone?: Tone) => void>(() => undefined)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const push = useCallback((text: string, tone: Tone = 'success') => {
    const id = Date.now() + Math.random()
    setToasts((t) => [...t, { id, text, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}

/** Valor que solo cambia cuando se deja de escribir durante ``ms`` milisegundos. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}
