// Tipos de la API del portal Low-Code (/api/automation, ADR-020).
import type { Page } from '../lib/types'

export type Source = { enabled: boolean; reachable: boolean; problem: string | null }

export type AutomationStatus = Source & {
  published: number
  active: number
  candidates: number | null
  editor_url: string | null
}

export type Workflow = {
  id: string
  name: string
  active: boolean
  launchable: boolean
  tags: string[]
  updated_at: string | null
}

export type FieldType = 'text' | 'textarea' | 'number' | 'boolean' | 'date' | 'select'

export type FieldDef = {
  name: string
  label: string
  type: FieldType
  required?: boolean
  options?: string[]
  help?: string | null
}

export type Category = 'ciclo_comercial' | 'back_office' | 'plataforma'

export type CatalogItem = {
  id: number
  title: string
  description: string | null
  category: Category
  fields: FieldDef[]
  active: boolean
  launchable: boolean
  updated_at: string | null
}

export type CatalogPage = Page<CatalogItem> & { source: Source }

export type EntryStatus = 'draft' | 'in_review' | 'published' | 'retired'

export type Check = { code: string; level: 'error' | 'warning'; message: string; node: string | null }

export type Entry = {
  id: number
  workflow_id: string
  title: string
  description: string | null
  category: Category
  fields: FieldDef[]
  status: EntryStatus
  checks: Check[]
  checked_at: string | null
  submitted_at: string | null
  reviewed_at: string | null
  review_note: string | null
  published_at: string | null
  created_at: string
  version: number
  input_names?: string[] | null
}

export type Candidate = Workflow & { entry_id: number | null }

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed'

export type Run = {
  id: number
  entry_id: number | null
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

// Monitorización (fase L4)
export type WorkflowHealth = {
  workflow_id: string
  workflow_name: string | null
  runs: number
  succeeded: number
  failed: number
  open: number
  success_rate: number | null
  avg_seconds: number | null
  last_run_at: string | null
  open_incidents: number
}

export type Incident = {
  id: number
  workflow_id: string
  workflow_name: string | null
  execution_id: string | null
  mode: string | null
  node: string | null
  message: string | null
  run_id: number | null
  status: 'open' | 'resolved'
  created_at: string
  resolved_by: number | null
  resolved_at: string | null
  resolution_note: string | null
  version: number
}
