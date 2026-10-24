// Usuarios: búsqueda, filtros en la URL y alta de cuentas nuevas.
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtRelative } from '../lib/format'
import type { Page } from '../lib/types'
import { Badge, Empty, ErrorBox, Field, Modal, Pager, Spinner, errorMessage, useDebounced } from '../components/ui'
import { APP_NAMES } from './labels'
import type { AdminUser } from './types'

export const USER_STATUS: Record<string, string> = { active: 'Activas', inactive: 'Desactivadas' }

export function UserStatus({ user }: { user: AdminUser }) {
  if (!user.is_active) return <Badge>Desactivada</Badge>
  if (user.locked_until && new Date(user.locked_until) > new Date()) return <Badge tone="warning">Bloqueada</Badge>
  return <Badge tone="success">Activa</Badge>
}

function NewUser({ onClose, onSaved }: { onClose: () => void; onSaved: (u: AdminUser) => void }) {
  const [form, setForm] = useState({ email: '', full_name: '', password: '' })
  const save = useMutation({
    mutationFn: () => api<{ user: AdminUser }>('/api/admin/users', { body: form }),
    onSuccess: (r) => onSaved(r.user),
  })
  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate()
  }
  return (
    <Modal title="Nueva persona" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <Field label="Nombre completo">
          <input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required maxLength={255} autoFocus />
        </Field>
        <Field label="Correo">
          <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required maxLength={255} />
        </Field>
        <Field label="Contraseña inicial" hint="Mínimo 12 caracteres. Compártela por un canal seguro; la persona puede cambiarla en «Mi cuenta».">
          <input
            type="password"
            autoComplete="new-password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
            minLength={12}
          />
        </Field>
        <p className="muted field-hint">La cuenta se crea sin acceso. Después le das un rol en cada aplicación.</p>
        {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
        <div className="actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button className="btn btn-primary" disabled={save.isPending}>
            Crear
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function Users() {
  const { can } = useAuth()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [text, setText] = useState(params.get('q') ?? '')
  const [creating, setCreating] = useState(false)
  const q = useDebounced(text.trim(), 300)
  const status = params.get('status') ?? ''
  const app = params.get('app') ?? ''
  const page = Number(params.get('page') ?? 1)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['admin', 'users', q, status, app, page],
    queryFn: () => api<Page<AdminUser>>('/api/admin/users', { query: { q, status, app, page } }),
    placeholderData: keepPreviousData,
  })
  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    setParams(next)
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Usuarios</h1>
          <p className="muted">Quién entra en la plataforma y con qué rol en cada aplicación.</p>
        </div>
        {can('users', 'write') && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            Nueva persona
          </button>
        )}
      </header>
      <div className="toolbar">
        <input type="search" className="grow" placeholder="Buscar por nombre o correo" value={text} onChange={(e) => setText(e.target.value)} />
        <select value={status} onChange={(e) => setFilter('status', e.target.value)} aria-label="Estado">
          <option value="">Todas</option>
          {Object.entries(USER_STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select value={app} onChange={(e) => setFilter('app', e.target.value)} aria-label="Aplicación">
          <option value="">Cualquier aplicación</option>
          {Object.entries(APP_NAMES).map(([k, v]) => (
            <option key={k} value={k}>
              Con acceso a {v}
            </option>
          ))}
        </select>
      </div>
      {isLoading && <Spinner />}
      {error && <ErrorBox error={error} onRetry={() => void refetch()} />}
      {data && !data.items.length && <Empty title="Nadie coincide con la búsqueda" />}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Persona</th>
                <th>Accesos</th>
                <th>Estado</th>
                <th>MFA</th>
                <th>Último acceso</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((u) => (
                <tr key={u.id}>
                  <td>
                    <Link to={`/users/${u.id}`} className="row-title">
                      {u.full_name}
                    </Link>
                    <div className="row-sub">{u.email}</div>
                  </td>
                  <td>
                    <span className="tag-list">
                      {u.is_superadmin && <Badge tone="accent">Superadmin</Badge>}
                      {u.memberships
                        .filter((m) => m.is_active)
                        .map((m) => (
                          <Badge key={m.app} title={APP_NAMES[m.app] ?? m.app}>
                            {APP_NAMES[m.app] ?? m.app}: {m.role_name}
                          </Badge>
                        ))}
                      {!u.is_superadmin && !u.memberships.some((m) => m.is_active) && <span className="muted">Sin acceso</span>}
                    </span>
                  </td>
                  <td>
                    <UserStatus user={u} />
                  </td>
                  <td>{u.mfa_enabled ? 'Sí' : <span className="muted">No</span>}</td>
                  <td>{u.last_login_at ? fmtRelative(u.last_login_at) : <span className="muted">Nunca</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && (
        <Pager
          pagination={data.pagination}
          onPage={(p) => {
            const next = new URLSearchParams(params)
            next.set('page', String(p))
            setParams(next)
          }}
        />
      )}
      {creating && <NewUser onClose={() => setCreating(false)} onSaved={(u) => navigate(`/users/${u.id}`)} />}
    </div>
  )
}
