// Roles y permisos: matriz módulo × acción por aplicación, con un rol editable cada vez.
// Los cambios se aplican en la siguiente petición de cada persona (la caché se invalida).
import { useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { ErrorBox, Spinner, errorMessage, useToast } from '../components/ui'
import { ACTION_NAMES, AI_MODULE_NAMES, APP_NAMES, MODULE_NAMES } from './labels'
import type { AppCatalog, Role } from './types'
import { Tabs } from './common'

type Catalog = { items: AppCatalog[]; ai_modules: string[] }
type Draft = { role: Role; permissions: Record<string, string[]> }
const AI_KEY = 'ai_modules_access'
const ACTION_ORDER = ['read', 'write', 'upload', 'delete', 'export', 'generate', 'send', 'approve', 'manage']
const byOrder = (a: string, b: string) => (ACTION_ORDER.indexOf(a) + 1 || 99) - (ACTION_ORDER.indexOf(b) + 1 || 99)

function has(perms: Record<string, string[]>, module: string, action: string) {
  return perms[module]?.includes(action) ?? false
}

export default function Roles() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [draft, setDraft] = useState<Draft | null>(null)
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['admin', 'apps'],
    queryFn: () => api<Catalog>('/api/admin/apps'),
  })
  const save = useMutation({
    mutationFn: (d: Draft) =>
      api<Role>(`/api/admin/roles/${d.role.id}`, { method: 'PATCH', body: { version: d.role.version, permissions: d.permissions } }),
    onSuccess: (role) => {
      setDraft(null)
      toast(`Permisos de «${role.name}» guardados.`)
      void qc.invalidateQueries({ queryKey: ['admin', 'apps'] })
    },
  })

  if (isLoading) return <Spinner />
  if (error) return <ErrorBox error={error} onRetry={() => void refetch()} />
  if (!data) return null
  const appCode = params.get('app') ?? data.items[0]?.code
  const app = data.items.find((a) => a.code === appCode) ?? data.items[0]
  if (!app) return null
  const showAI = app.code === 'operations' || app.code === 'analytics'
  const editable = can('roles', 'write')

  function toggle(module: string, action: string) {
    if (!draft) return
    const current = draft.permissions[module] ?? []
    const next = current.includes(action) ? current.filter((a) => a !== action) : [...current, action]
    setDraft({ ...draft, permissions: { ...draft.permissions, [module]: next } })
  }

  function cell(role: Role, module: string, action: string, label: string) {
    const editing = draft?.role.id === role.id
    const perms = editing ? draft.permissions : role.permissions
    const on = role.is_admin || has(perms, module, action)
    if (editing) {
      return (
        <td key={role.id} className="perm-cell perm-editing">
          <input type="checkbox" checked={on} onChange={() => toggle(module, action)} aria-label={`${role.name}: ${label}`} />
        </td>
      )
    }
    return (
      <td key={role.id} className={`perm-cell${on ? ' perm-on' : ''}`}>
        <span aria-label={on ? 'Sí' : 'No'}>{on ? '✓' : '·'}</span>
      </td>
    )
  }

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>Roles y permisos</h1>
          <p className="muted">
            Qué puede hacer cada rol en cada aplicación. Los permisos se leen de aquí en cada petición: un cambio se aplica
            enseguida a todas las personas con ese rol.
          </p>
        </div>
      </header>
      <Tabs
        tabs={data.items.map((a) => ({ key: a.code, label: APP_NAMES[a.code] ?? a.name }))}
        value={app.code}
        onChange={(code) => {
          setDraft(null)
          setParams({ app: code })
        }}
      />
      {save.error && <p className="notice notice-error">{errorMessage(save.error)}</p>}
      <div className="table-wrap">
        <table className="table perm-table">
          <thead>
            <tr>
              <th>Permiso</th>
              {app.roles.map((r) => (
                <th key={r.id} className="perm-role">
                  <div>{r.name}</div>
                  <div className="row-sub">
                    {r.members} {r.members === 1 ? 'persona' : 'personas'}
                  </div>
                  {editable && !r.is_admin && (
                    <div className="perm-actions">
                      {draft?.role.id === r.id ? (
                        <>
                          <button className="btn btn-small btn-primary" disabled={save.isPending} onClick={() => save.mutate(draft)}>
                            Guardar
                          </button>
                          <button className="btn btn-small btn-ghost" onClick={() => setDraft(null)}>
                            Cancelar
                          </button>
                        </>
                      ) : (
                        <button
                          className="btn btn-small btn-ghost"
                          disabled={!!draft}
                          onClick={() => setDraft({ role: r, permissions: structuredClone(r.permissions) })}
                        >
                          Editar
                        </button>
                      )}
                    </div>
                  )}
                  {r.is_admin && <div className="row-sub">Todo</div>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {app.modules.map((m) => (
              <ModuleRows key={m.module} title={MODULE_NAMES[m.module] ?? m.module}>
                {[...m.actions].sort(byOrder).map((action) => {
                  const label = `${MODULE_NAMES[m.module] ?? m.module}: ${ACTION_NAMES[action] ?? action}`
                  return (
                    <tr key={action}>
                      <td className="perm-action">{ACTION_NAMES[action] ?? action}</td>
                      {app.roles.map((r) => cell(r, m.module, action, label))}
                    </tr>
                  )
                })}
              </ModuleRows>
            ))}
            {showAI && (
              <ModuleRows title="Módulos de IA">
                {data.ai_modules.map((mod) => (
                  <tr key={mod}>
                    <td className="perm-action">{AI_MODULE_NAMES[mod] ?? mod}</td>
                    {app.roles.map((r) => cell(r, AI_KEY, mod, AI_MODULE_NAMES[mod] ?? mod))}
                  </tr>
                ))}
              </ModuleRows>
            )}
          </tbody>
        </table>
      </div>
      <p className="field-hint">
        «Gestionar» permite modificar lo que es de otras personas. Los roles de administrador tienen todos los permisos de su
        aplicación y no se editan.
      </p>
    </div>
  )
}

function ModuleRows({ title, children }: { title: string; children: ReactNode }) {
  return (
    <>
      <tr className="perm-module">
        <th colSpan={99} scope="rowgroup">
          {title}
        </th>
      </tr>
      {children}
    </>
  )
}
