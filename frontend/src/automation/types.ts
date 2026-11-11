// Tipos de la API del portal Low-Code (/api/automation, ADR-020).
import type { Page } from '../lib/types'

export type Source = { enabled: boolean; reachable: boolean; problem: string | null }

export type AutomationStatus = Source & { published: number; active: number; editor_url: string | null }

export type Workflow = { id: string; name: string; active: boolean; tags: string[]; updated_at: string | null }

export type CatalogPage = Page<Workflow> & { source: Source }
