// Tipos de la API del portal Low-Code (/api/automation, ADR-020).
import type { Page } from '../lib/types'

export type Source = { enabled: boolean; reachable: boolean; problem: string | null }

export type AutomationStatus = Source & { published: number; active: number; editor_url: string | null }

export type Workflow = {
  id: string
  name: string
  active: boolean
  launchable: boolean
  tags: string[]
  updated_at: string | null
}

export type CatalogPage = Page<Workflow> & { source: Source }

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export type Run = {
  id: number
  workflow_id: string
  workflow_name: string
  status: RunStatus
  error: string | null
  requested_by: number | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export type RunDetail = Run & { input: Record<string, unknown>; result: Record<string, unknown> | null }
