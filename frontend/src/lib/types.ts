// Tipos de las respuestas de la API (contrato en docs/api.md).

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
export type ActiveApp = {
  code: string
  role: string
  is_admin: boolean
  permissions: Record<string, string[]>
}

export type Pagination = { page: number; per_page: number; total: number; pages: number }
export type Page<T> = { items: T[]; pagination: Pagination }

// ---------------------------------------------------------------- Oportunidades
export type OpportunitySummary = {
  id: number
  code: string | null
  title: string
  status: string
  phase: string
  client_id: number | null
  client_name: string | null
  source: string | null
  service_line: string | null
  estimated_value_eur: string | null
  probability: number | null
  deadline: string | null
  owner_user_id: number | null
  relevance_score: number | null
  version: number
  updated_at: string
}

export type ScoreBreakdown = Record<string, number | string | null>

export type Opportunity = OpportunitySummary & {
  description: string | null
  sector: string | null
  contracting_entity: string | null
  cpv_codes: string[]
  external_id: string | null
  published_at: string | null
  link: string | null
  score_breakdown: ScoreBreakdown | null
  ai_summary: string | null
  go_no_go: Record<string, unknown> | null
  allowed_transitions: string[]
  documents: { document_id: number; role: string; title: string; processing_status: string }[]
  proposals: { id: number; title: string; proposal_type: string; status: string; version_number: number }[]
  created_at: string
}

export type SearchHit = OpportunitySummary & {
  contracting_entity: string | null
  published_at: string | null
  score: number | null
  highlight: { title: string | null; snippet: string | null }
}

export type Facets = Record<string, Record<string, number>>

export type OpportunitySearch = Page<SearchHit> & {
  engine: 'meilisearch' | 'mysql'
  facets: Facets | null
  notes?: string[]
  query_log_id?: number | null
  processing_ms?: number
}

export type SimilarOpportunity = {
  opportunity_id: number
  title: string
  status: string
  contracting_entity: string | null
  score: number
  relevance_score: number | null
}

// ---------------------------------------------------------------- Análisis
export type Requirement = { requirement: string; kind: string; meets: string; evidence?: string }
export type Risk = { description: string; severity: string; mitigation?: string }
export type Analysis = {
  id: number
  subject_type: 'document' | 'opportunity'
  subject_id: number
  status: 'queued' | 'running' | 'done' | 'failed'
  verdict: 'GO' | 'NO_GO' | 'CONDITIONAL' | null
  confidence: number | null
  model: string | null
  error: string | null
  truncated: boolean
  created_at: string
  completed_at: string | null
  result: {
    summary?: string
    verdict?: string
    confidence?: number
    scores?: Record<string, number>
    requirements?: Requirement[]
    risks?: Risk[]
    conditions?: string[]
    next_steps?: string[]
    missing_information?: string[]
  } | null
}

// ---------------------------------------------------------------- Documentos
export type DocumentSummary = {
  id: number
  title: string
  doc_type: string | null
  original_filename: string | null
  mime_type: string | null
  file_size_bytes: number | null
  processing_status: 'pending' | 'processing' | 'processed' | 'failed'
  index_status: string
  is_current_version: boolean
  is_restricted: boolean
  version_number: number
  ai_summary: string | null
  created_at: string
  created_by: number | null
  version: number
}

export type DocumentDetail = DocumentSummary & {
  processing_error: string | null
  processed_at: string | null
  text_length: number | null
  text_preview: string | null
  ai_keywords: string[] | null
  ai_entities: Record<string, unknown> | null
  ai_enriched_at: string | null
  allowed_roles: string[] | null
  embedding_model: string | null
  vector_count?: number | null
  opportunities: { opportunity_id: number; role: string }[]
  versions?: { id: number; version_number: number; created_at: string; is_current_version: boolean }[]
}

export type Source = {
  n: number
  document_id: number
  title: string
  doc_type: string | null
  score: number
  page: number | null
  excerpt: string
  cited: boolean
}
export type RagAnswer = {
  answer: string
  sufficient_context: boolean
  citations: { source: number; quote?: string }[]
  sources: Source[]
  usage_log_id: number | null
  model?: string
}

// ---------------------------------------------------------------- Propuestas
export type ProposalSummary = {
  id: number
  title: string
  proposal_type: string
  status: string
  opportunity_id: number
  opportunity_title: string | null
  owner_user_id: number | null
  total_amount_eur: string | null
  generation_status: string
  sent_at: string | null
  updated_at: string
  version: number
  version_number: number
}

export type Section = {
  id: number
  key: string
  title: string
  position: number
  ai_content: string | null
  edited_content: string | null
  final_content: string | null
  version: number
}

export type Attachment = {
  id: number
  kind: string
  filename: string
  mime_type: string | null
  file_size_bytes: number | null
  created_at: string
}

export type Review = {
  id: number
  kind: string
  decision: string
  comment: string | null
  reviewer_user_id: number
  created_at: string
}

export type Proposal = ProposalSummary & {
  allowed_transitions: string[]
  required_reviews: string[]
  review_round: number
  reviews: Review[]
  sections: Section[]
  attachments: Attachment[]
  generation_error: string | null
  generated_at: string | null
  reviewed_at: string | null
  created_at: string
}

export type Template = {
  id: number
  name: string
  proposal_type: string
  description: string | null
  sections: { key: string; title: string; order: number }[]
}

// ---------------------------------------------------------------- Clientes y talento
export type ClientSummary = {
  id: number
  name: string
  sector: string | null
  segment: string | null
  risk_level: string | null
  owner_user_id: number | null
  updated_at: string
  version: number
}
export type Contact = {
  id: number
  full_name: string
  email: string | null
  phone: string | null
  position: string | null
  is_primary: boolean
  version: number
}
export type Project = {
  id: number
  name: string
  description: string | null
  status: string
  start_date: string | null
  end_date: string | null
  budget_eur: string | null
  version: number
}
export type Client = ClientSummary & {
  tax_id: string | null
  website: string | null
  notes: string | null
  open_opportunities: number
  contacts: Contact[]
  projects: Project[]
  created_at: string
}

export type ProfileSummary = {
  id: number
  full_name: string
  headline: string | null
  family: string | null
  seniority: string | null
  years_experience: number | null
  is_available: boolean
  skills: string[]
  version: number
}
export type Profile = Omit<ProfileSummary, 'skills'> & {
  email: string | null
  summary: string | null
  skills: { name: string; level: number | null; years: number | null }[]
  experiences: {
    company: string
    role: string | null
    start_date: string | null
    end_date: string | null
    description: string | null
    technologies: string[]
  }[]
  updated_at: string
}

// ---------------------------------------------------------------- Bandeja
export type Notification = {
  id: number
  type: string
  title: string
  body: string | null
  link: string | null
  priority: string
  read_at: string | null
  created_at: string
}
export type Alert = {
  id: number
  alert_type: string
  opportunity_id: number | null
  score: number | null
  message: string | null
  resolved_at: string | null
  created_at: string
}

// ---------------------------------------------------------------- Búsqueda y asistente
export type QuickSearch = {
  query: string
  engine: string
  groups: {
    type: 'opportunities' | 'documents' | 'clients'
    total: number
    items: { id: number; title: string; subtitle: string; highlight: string; status?: string }[]
  }[]
}

export type Intent = {
  type: 'CHAT_RAG' | 'AGENT_TOOLS' | 'WORKFLOW' | 'OFF_TOPIC'
  subtype: string | null
  confidence: number
  layer: string
}

export type AssistantResponse =
  | ({ type: 'search_results'; intent: Intent; target: string; filters: Record<string, unknown> } & Page<
      SearchHit & { name?: string }
    >)
  | ({ type: 'rag_answer'; intent: Intent } & RagAnswer)
  | {
      type: 'workflow_suggestion'
      intent: Intent
      action: string
      target: { kind: string; id: number; title: string; code?: string | null; proposal_id?: number } | null
      message: string
      confirm: { method: string; path: string; body?: Record<string, unknown> } | null
    }
  | { type: 'off_topic'; intent: Intent; message: string }

// ---------------------------------------------------------------- Copiloto
export type Conversation = {
  id: number
  title: string
  message_count: number
  has_summary: boolean
  created_at: string
  last_message_at: string | null
}

export type ToolUse = { id?: string; name: string; title?: string; summary?: string; ok?: boolean; ms?: number }
export type PendingAction = { id: string; name: string; title: string; summary: string; input: Record<string, unknown> }
export type Reference = { kind: string; id: number; title: string; code?: string | null; status?: string }

export type ChatMessage = {
  id: number
  role: 'user' | 'assistant'
  content: string
  intent: string | null
  run_id: string | null
  created_at: string
  meta: {
    tools?: ToolUse[]
    references?: Reference[]
    sources?: Source[]
    approval?: { run_id: string; actions: PendingAction[]; status: 'pending' | 'approved' | 'rejected' }
    error?: boolean
    usage_log_id?: number | null
    [key: string]: unknown
  }
}

export type Memory = {
  id: number
  category: string
  content: string
  source: 'auto' | 'user'
  access_count: number
  created_at: string
  updated_at: string
  last_accessed_at: string | null
}
