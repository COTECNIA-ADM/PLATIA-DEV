// Respuestas de /api/admin (fase 6b).
export type Membership = { app: string; role: string; role_name: string; is_active: boolean }

export type AdminUser = {
  id: number
  email: string
  full_name: string
  status: string
  is_active: boolean
  is_superadmin: boolean
  mfa_enabled: boolean
  locked_until: string | null
  last_login_at: string | null
  created_at: string | null
  memberships: Membership[]
}

export type Role = {
  id: number
  code: string
  name: string
  is_admin: boolean
  permissions: Record<string, string[]>
  members: number
  version: number
  updated_at: string | null
}

export type AppCatalog = {
  code: string
  name: string
  description: string | null
  modules: { module: string; actions: string[] }[]
  roles: Role[]
}

export type AuditEntry = {
  id: number
  action: string
  severity: string
  user_id: number | null
  user_email: string | null
  resource_type: string | null
  resource_id: string | null
  ip_address: string | null
  request_id: string | null
  details: Record<string, unknown> | null
  created_at: string
}

export type FailedTask = {
  id: number
  task_id: string
  task_name: string
  queue: string | null
  error_type: string | null
  error_message: string | null
  args: unknown[] | null
  retries: number
  failed_at: string
  reviewed: boolean
  reviewed_by: number | null
  reviewed_at: string | null
  requeued_task_id: string | null
}

export type ServiceConfig = {
  service_type: string
  provider: string
  model_name: string
  fallback_provider: string | null
  fallback_model: string | null
  max_tokens: number
  effort: string | null
  prompt_name: string | null
  description: string | null
  is_active: boolean
  updated_at: string | null
}

export type Pricing = {
  provider: string
  model_name: string
  effective_date: string
  input_usd_per_mtok: string
  output_usd_per_mtok: string
  cache_read_usd_per_mtok: string | null
  cache_write_usd_per_mtok: string | null
}

export type Budget = {
  id: number
  scope: 'global' | 'service' | 'user'
  scope_id: string
  daily_limit_usd: string | null
  monthly_limit_usd: string | null
  alert_threshold_pct: number
  throttle_threshold_pct: number
  block_threshold_pct: number
  throttle_delay_seconds: number
  is_active: boolean
  spent_today_usd: string
  spent_month_usd: string
}

export type UsageRow = {
  service_type: string
  model: string
  calls: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cost_usd: string
  errors: number
  fallbacks: number
  error_rate: number
  avg_latency_ms: number | null
}

export type UsageCall = {
  id: number
  service_type: string
  model: string
  input_tokens: number
  output_tokens: number
  cost_usd: string
  latency_ms: number | null
  success: boolean
  error_type: string | null
  stop_reason: string | null
  is_fallback: boolean
  user_id: number | null
  correlation_id: string | null
  created_at: string
}

export type Baseline = { service_type: string; task_name: string; human_time_minutes: number; human_hourly_cost_eur: string }

export type QualityRow = {
  service_type: string
  reviewer_type: string
  count: number
  composite: number | null
  faithfulness: number | null
  relevance: number | null
  hallucination: number | null
  user_rating: number | null
}

export type Compliance = {
  days: number
  events: Record<string, number>
  outputs_scanned: number
  outputs_with_pii: number
  prompt_integrity: { name: string; version: number; stored_hash: string; current_hash: string }[]
}

export type RagCollections = {
  documents_by_index_status: Record<string, number>
  qdrant:
    | {
        collections: { collection: string; description: string; physical: string; points: number }[]
        embedding_model: string
      }
    | { error: string }
}

export type AIHealth = {
  status: string
  checks?: Record<string, string>
  model?: string
  embedding?: { provider: string; model: string; dims: number }
  error?: string
}

export type Prompt = {
  id: number
  name: string
  version: number
  service_type: string | null
  description: string | null
  notes: string | null
  is_active: boolean
  variables: string[]
  content_hash: string
  created_by: number | null
  created_at: string
  archived_at: string | null
  integrity_ok?: boolean
  system_prompt?: string
  user_template?: string | null
}

export type AgentSummary = {
  id: number
  slug: string
  name: string
  description: string | null
  agent_type: 'conversational' | 'specialist'
  status: 'draft' | 'active' | 'archived'
  llm_service_type: string
  prompt_name: string
  tool_count: number
  version: number
  version_number: number
  updated_at: string
}

export type AgentTool = {
  tool_name: string
  approval_level: 'auto' | 'notify' | 'approve'
  min_level: 'auto' | 'notify' | 'approve'
  sort_order: number
  config: Record<string, unknown> | null
}

export type Agent = AgentSummary & {
  max_iterations: number
  max_tool_calls: number
  timeout_seconds: number
  intent_keywords: string[]
  success_criteria: string | null
  test_cases: { input: string; expect_tools: string[] }[]
  tools: AgentTool[]
  prompt: { system_prompt: string; context_template: string | null; version: number } | null
}

export type ToolInfo = {
  name: string
  title: string
  description: string
  permission: string
  ai_module: string | null
  min_level: 'auto' | 'notify' | 'approve'
}

export type AgentMetrics = {
  days: number
  metrics: {
    runs: number
    completion_rate: number | null
    error_rate: number | null
    avg_iterations: number | null
    avg_tool_calls: number | null
    avg_cost_usd: string | null
    p95_duration_ms: number | null
    approval_rejection_rate: number | null
    max_iterations_rate: number | null
    stop_reasons: Record<string, number>
    tools: Record<string, { calls: number; errors: number; avg_ms: number }>
  }
  alerts: { metric: string; value: number; threshold: number }[]
  thresholds: Record<string, number>
}

export type AgentRun = {
  run_id: string
  agent_id: number
  agent_version: number
  mode: string
  status: string
  stop_reason: string | null
  iterations: number
  input_tokens: number
  output_tokens: number
  cost_usd: string
  duration_ms: number | null
  error: string | null
  user_id: number | null
  tool_calls: { name: string; ok: boolean; ms: number; level: string; approved?: boolean }[]
  created_at: string
}

export type AgentTestResult = {
  run_id: string
  text: string
  trace: ({ event: string } & Record<string, unknown>)[]
  tools_used: string[]
  available_tools: string[]
  summary: Record<string, unknown>
  check: { expected_tools: string[]; missing: string[]; passed: boolean } | null
}

export type IntentPattern = {
  id: number
  intent: string
  subtype: string
  pattern: string
  priority: number
  description: string | null
  is_active: boolean
  updated_at: string
}

export type SearchQuality = {
  days: number
  totals: Record<string, number>
  intents: { intent: string; count: number; avg_confidence: number | null }[]
  layers: Record<string, number>
  layer1_share_pct: number | null
  classify_ms: { p50: number | null; p95: number | null }
  zero_results_pct: number | null
  click_through_rate_pct: number | null
  reformulation_rate_pct: number | null
  median_seconds_to_first_click: number | null
  ratings: { average: number | null; count: number }
  top_zero_result_queries: { query: string; count: number }[]
  misclassified: { classified: string; expected: string; count: number }[]
  warnings: string[]
}

export type SearchIndex = {
  index: string
  uid: string
  documents: number | null
  mysql_count: number
  in_sync: boolean
  is_indexing: boolean
  pending: number
  last_rebuild: string | null
}

export type IntentTest = {
  normalized: string
  result: { type: string; subtype: string | null; confidence: number; layer: string; latency_ms: number; reasoning?: string }
  layer1: { type: string; subtype: string | null; confidence: number; layer: string; matched: IntentPattern[] }
  llm_filters: Record<string, unknown> | null
}

export type AgentVersion = { version_number: number; notes: string | null; created_by: number | null; created_at: string; snapshot: Record<string, unknown> }
export type Queues = { queues: Record<string, number | null>; known_queues: string[] }
