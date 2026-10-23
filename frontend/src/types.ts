export type Status = 'healthy' | 'degraded' | 'unhealthy'

export type ServiceStatus = { name: string; status: Status; detail?: string; error?: string }

export type HealthResponse = { status: Status; services: ServiceStatus[] }

export type AppAccess = { code: string; name: string; role: string; is_admin: boolean }

export type User = {
  id: number
  email: string
  full_name: string
  mfa_enabled: boolean
  is_superadmin: boolean
  apps: AppAccess[]
}
