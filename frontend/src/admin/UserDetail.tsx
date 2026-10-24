// Ficha de una persona: rol en cada aplicación, alta y baja, MFA y datos de IA (RGPD).
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime } from '../lib/format'
import { Badge, ErrorBox, Spinner, errorMessage, useToast } from '../components/ui'
import { ConfirmDialog, saveJson, type Confirm } from './common'
import { APP_NAMES } from './labels'
import type { AdminUser, AppCatalog } from './types'
import { UserStatus } from './Users'

export default function UserDetail() {
  const { id } = useParams()
  const { can, user: me } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [confirm, setConfirm] = useState<Confirm | null>(null)
  const key = ['admin', 'user', id]
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: key,
    queryFn: () => api<{ user: AdminUser }>(`/api/admin/users/${id}`).then((r) => r.user),
  })
  const apps = useQuery({
    queryKey: ['admin', 'apps'],
    queryFn: () => api<{ items: AppCatalog[] }>('/api/admin/apps'),
    enabled: can('roles', 'read'),
  })

  function updated(u: AdminUser) {
    qc.setQueryData(key, u)
    void qc.invalidateQueries({ queryKey: ['admin', 'users'] })
    void qc.invalidateQueries({ queryKey: ['admin', 'apps'] })
  }
  const setRole = useMutation({
    mutationFn: ({ app, role }: { app: string; role: string }) =>
      api<{ user: AdminUser }>(`/api/admin/users/${id}/memberships/${app}`, { method: 'PUT', body: { role } }),
    onSuccess: (r) => {
      updated(r.user)
      toast('Rol guardado. Se aplica en su próxima petición.')
    },
    onError: (e) => toast(errorMessage(e), 'danger'),
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!data) return null
  const u = data
  const isMe = me?.id === u.id
  const canRoles = can('roles', 'write')
  const canUsers = can('users', 'write')
  const post = (path: string) => () => api<{ user: AdminUser }>(`/api/admin/users/${u.id}${path}`, { method: 'POST' }).then((r) => updated(r.user))

  return (
    <div className="page">
      <nav className="crumbs">
        <Link to="/users">Usuarios</Link> / {u.full_name}
      </nav>
      <header className="page-head">
        <div>
          <h1>{u.full_name}</h1>
          <p className="muted">
            {u.email} · <UserStatus user={u} /> {u.is_superadmin && <Badge tone="accent">Superadmin</Badge>}
          </p>
        </div>
        {canUsers && !isMe && (
          <div className="btn-row">
            {u.is_active ? (
              <button
                className="btn btn-danger"
                onClick={() =>
                  setConfirm({
                    title: 'Desactivar cuenta',
                    text: `${u.full_name} dejará de poder entrar y se cerrarán sus sesiones abiertas. Su trabajo se conserva y puedes reactivarla cuando quieras.`,
                    action: 'Desactivar',
                    danger: true,
                    run: post('/deactivate'),
                  })
                }
              >
                Desactivar
              </button>
            ) : (
              <button className="btn btn-primary" onClick={() => setConfirm({ title: 'Reactivar cuenta', text: `${u.full_name} podrá volver a entrar con su contraseña y los roles que ya tenía.`, action: 'Reactivar', run: post('/reactivate') })}>
                Reactivar
              </button>
            )}
          </div>
        )}
      </header>

      <div className="detail-grid">
        <section className="card">
          <h2>Acceso a las aplicaciones</h2>
          {u.is_superadmin && <p className="notice">Es superadmin: tiene acceso a todo, sin depender de los roles.</p>}
          {apps.isLoading && <Spinner />}
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Aplicación</th>
                  <th>Rol</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(apps.data?.items ?? Object.keys(APP_NAMES).map((code) => ({ code, name: APP_NAMES[code], roles: [] }))).map((app) => {
                  const m = u.memberships.find((x) => x.app === app.code && x.is_active)
                  const roles = 'roles' in app ? app.roles : []
                  return (
                    <tr key={app.code}>
                      <td>{APP_NAMES[app.code] ?? app.name}</td>
                      <td>
                        {canRoles && roles.length ? (
                          <select
                            aria-label={`Rol en ${APP_NAMES[app.code] ?? app.name}`}
                            value={m?.role ?? ''}
                            disabled={setRole.isPending}
                            onChange={(e) => e.target.value && setRole.mutate({ app: app.code, role: e.target.value })}
                          >
                            <option value="">Sin acceso</option>
                            {roles.map((r) => (
                              <option key={r.code} value={r.code}>
                                {r.name}
                              </option>
                            ))}
                          </select>
                        ) : m ? (
                          m.role_name
                        ) : (
                          <span className="muted">Sin acceso</span>
                        )}
                      </td>
                      <td className="num">
                        {canRoles && m && !(isMe && app.code === 'admin') && (
                          <button
                            className="btn btn-small btn-ghost"
                            onClick={() =>
                              setConfirm({
                                title: 'Quitar acceso',
                                text: `${u.full_name} dejará de ver ${APP_NAMES[app.code] ?? app.name}. Puedes volver a darle un rol cuando quieras.`,
                                action: 'Quitar acceso',
                                danger: true,
                                run: () =>
                                  api<{ user: AdminUser }>(`/api/admin/users/${u.id}/memberships/${app.code}`, { method: 'DELETE' }).then((r) =>
                                    updated(r.user),
                                  ),
                              })
                            }
                          >
                            Quitar
                          </button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {can('roles', 'read') && (
            <p className="field-hint">
              Qué puede hacer cada rol: <Link to="/roles">Roles y permisos</Link>.
            </p>
          )}
        </section>

        <aside className="stack">
          <section className="card">
            <h2>Cuenta</h2>
            <dl className="facts facts-compact">
              <span className="facts-pair">
                <dt>Alta</dt>
                <dd>{fmtDateTime(u.created_at)}</dd>
              </span>
              <span className="facts-pair">
                <dt>Último acceso</dt>
                <dd>{u.last_login_at ? fmtDateTime(u.last_login_at) : 'Nunca'}</dd>
              </span>
              {u.locked_until && new Date(u.locked_until) > new Date() && (
                <span className="facts-pair">
                  <dt>Bloqueada hasta</dt>
                  <dd>{fmtDateTime(u.locked_until)}</dd>
                </span>
              )}
              <span className="facts-pair">
                <dt>Verificación en dos pasos</dt>
                <dd>{u.mfa_enabled ? 'Activada' : 'No'}</dd>
              </span>
            </dl>
            {canUsers && !isMe && u.mfa_enabled && (
              <button
                className="btn btn-small"
                onClick={() =>
                  setConfirm({
                    title: 'Quitar la verificación en dos pasos',
                    text: 'Para quien ha perdido el móvil. Se cierran sus sesiones; al volver a entrar con la contraseña podrá activarla de nuevo desde «Mi cuenta».',
                    action: 'Quitar MFA',
                    danger: true,
                    run: post('/mfa/reset'),
                  })
                }
              >
                Quitar MFA
              </button>
            )}
            {can('audit', 'read') && (
              <p className="field-hint">
                <Link to={`/audit?user_id=${u.id}`}>Ver su actividad en auditoría</Link>
              </p>
            )}
          </section>

          {canUsers && (
            <section className="card">
              <h2>Datos de IA (RGPD)</h2>
              <p className="muted">
                Llamadas a modelos, búsquedas, conversaciones y memoria del copiloto de esta persona.
              </p>
              <div className="btn-row">
                <button
                  className="btn btn-small"
                  onClick={() =>
                    api(`/api/admin/ai/gdpr/users/${u.id}`)
                      .then((d) => saveJson(`datos-ia-usuario-${u.id}.json`, d))
                      .catch((e) => toast(errorMessage(e), 'danger'))
                  }
                >
                  Exportar
                </button>
                <button
                  className="btn btn-small btn-danger"
                  onClick={() =>
                    setConfirm({
                      title: 'Borrar los datos de IA',
                      text: 'Se borran sus conversaciones y la memoria del copiloto, y el resto de registros (llamadas, búsquedas, valoraciones) queda sin nada que la identifique. Los importes se conservan para la contabilidad. No se puede deshacer.',
                      action: 'Borrar',
                      danger: true,
                      run: () => api(`/api/admin/ai/gdpr/users/${u.id}/erase`, { method: 'POST' }).then(() => toast('Datos de IA borrados.')),
                    })
                  }
                >
                  Borrar
                </button>
              </div>
            </section>
          )}
        </aside>
      </div>
      {confirm && <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />}
    </div>
  )
}
