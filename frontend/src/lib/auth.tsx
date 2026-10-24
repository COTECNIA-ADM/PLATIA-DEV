// Sesión y permisos (Capítulo 17).
// Los permisos salen de /api/auth/me, que los lee de la base de datos (nunca del JWT).
// Ocultar un botón es solo comodidad: el backend vuelve a comprobarlo todo.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, refreshSession, setAccessToken } from './api'
import type { ActiveApp, User } from './types'

type Me = { user: User; active_app: ActiveApp }

type AuthState = {
  user: User | null
  app: ActiveApp | null
  loading: boolean
  expired: boolean
  /** ¿El rol permite esta acción en este módulo? */
  can: (module: string, action: string) => boolean
  /** ¿El rol tiene este módulo de IA (ai_modules_access)? */
  hasAI: (module: string) => boolean
  /** ¿Es el responsable o tiene la acción manage del módulo? */
  canModify: (module: string, ownerId: number | null | undefined) => boolean
  signedIn: (accessToken: string) => Promise<void>
  reload: () => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [expired, setExpired] = useState(false)

  const reload = useCallback(async () => {
    setMe(await api<Me>('/api/auth/me'))
  }, [])

  // Al abrir la página se intenta recuperar la sesión con la cookie de refresco
  useEffect(() => {
    void (async () => {
      if (await refreshSession()) await reload().catch(() => setMe(null))
      setLoading(false)
    })()
  }, [reload])

  // El cliente de la API avisa cuando el refresco falla: la sesión ha caducado
  useEffect(() => {
    const onExpired = () => {
      setMe(null)
      setExpired(true)
      queryClient.clear()
    }
    window.addEventListener('auth:expired', onExpired)
    return () => window.removeEventListener('auth:expired', onExpired)
  }, [queryClient])

  const signedIn = useCallback(
    async (token: string) => {
      setAccessToken(token)
      setExpired(false)
      await reload()
    },
    [reload],
  )

  const logout = useCallback(async () => {
    await api('/api/auth/logout', { method: 'POST' }).catch(() => undefined)
    setAccessToken(null)
    setMe(null)
    queryClient.clear()
  }, [queryClient])

  const value = useMemo<AuthState>(() => {
    const app = me?.active_app ?? null
    const can = (module: string, action: string) =>
      !!app && (app.is_admin || (app.permissions[module] ?? []).includes(action))
    return {
      user: me?.user ?? null,
      app,
      loading,
      expired,
      can,
      hasAI: (module) => !!app && (app.is_admin || (app.permissions.ai_modules_access ?? []).includes(module)),
      canModify: (module, ownerId) => can(module, 'manage') || (!!me && ownerId === me.user.id),
      signedIn,
      reload,
      logout,
    }
  }, [me, loading, expired, signedIn, reload, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth debe usarse dentro de AuthProvider')
  return ctx
}
