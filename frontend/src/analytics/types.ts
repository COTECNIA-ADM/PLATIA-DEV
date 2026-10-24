// Respuestas de /api/analytics (fase 6b).
export type Group = {
  key: string
  label: string
  open_count: number
  pipeline_eur: string
  won: number
  lost: number
  won_eur: string
  win_rate: number | null
}

export type Overview = {
  period: { months: number; from: string; to: string }
  filters: { service_line: string | null; sector: string | null }
  kpis: {
    open_count: number
    pipeline_eur: string
    weighted_pipeline_eur: string
    new_count: number
    won_count: number
    won_eur: string
    lost_count: number
    discarded_count: number
    win_rate: number | null
    proposals_sent: number
  }
  previous: {
    from: string
    to: string
    new_count: number
    won_count: number
    won_eur: string
    lost_count: number
    win_rate: number | null
    proposals_sent: number
    pipeline_eur: string | null
    weighted_pipeline_eur: string | null
    open_count: number | null
    pipeline_date: string | null
  }
  pipeline_history: { date: string; pipeline_eur: string; weighted_pipeline_eur: string; open_count: number }[]
  targets: { metric: TargetMetric; target: string; actual: string; progress: number | null; months: string[] }[]
  funnel: { phase: string; reached: number; reached_pct: number | null; open_count: number; open_eur: string }[]
  monthly: { month: string; new_count: number; new_eur: string; won_count: number; won_eur: string; lost_count: number }[]
  by_service_line: Group[]
  by_sector: Group[]
  heatmap: { sector: string; service_line: string; service_line_label: string; count: number; eur: string }[]
  top_clients: { client_id: number; name: string | null; open_count: number; pipeline_eur: string; won_eur: string }[]
  proposals: {
    by_status: Record<string, number>
    sent: number
    avg_days_to_send: number | null
    avg_review_rounds: number | null
  }
}

export type RoiService = {
  service_type: string
  tasks: number
  cost_eur: string
  hours_saved: number
  net_saving_eur: string
  roi_pct: number | null
  avg_user_rating: number | null
}

export type AIValue = {
  months: number
  roi: {
    from: string
    to: string
    services: RoiService[]
    total: { tasks: number; cost_eur: string; hours_saved: number; net_saving_eur: string; roi_pct: number | null }
  }
  monthly: { month: string; calls: number; cost_usd: string }[]
}

// ---------------------------------------------------------------- Fase 9a
export type TargetMetric = 'new_count' | 'new_eur' | 'won_count' | 'won_eur'
export type Dimension = 'demand' | 'traction' | 'economic' | 'right_to_win'

export type MarketCell = {
  sector: string
  service_line: string
  service_line_label: string
  total_score: number
  scores: Record<Dimension, number>
  data: {
    opportunities: number
    recent: number
    prior: number
    won: number
    lost: number
    avg_value_eur: string | null
    pipeline_eur: string
  }
}

export type MarketMap = {
  period: string
  calculated_at: string
  weights: Record<Dimension, number>
  lookback_months: number | null
  unclassified: number
  cells: MarketCell[]
  config: { weights: Record<Dimension, number>; lookback_months: number; version: number }
  periods: string[]
}

export type Competitor = {
  id: number
  name: string
  competitor_type: 'direct' | 'indirect' | 'substitute'
  website: string | null
  description: string | null
  strengths: string[]
  weaknesses: string[]
  opportunities: string[]
  threats: string[]
  service_lines: string[]
  sectors: string[]
  price_positioning: -1 | 0 | 1
  version: number
  updated_at: string
}

export type Target = {
  id: number
  metric: TargetMetric
  period: string
  service_line: string
  target_value: string
  version: number
  updated_at: string
}

export type ImportSheet = {
  rows: number
  create: number
  update: number
  error_count: number
  errors: { row: number; field: string | null; message: string }[]
}

export type ImportResult = {
  dry_run: boolean
  applied: boolean
  has_errors: boolean
  sheets: Record<string, ImportSheet>
}

export type AskAnswer = {
  answer: string
  sufficient_data: boolean
  usage_log_id: number
  model: string
  is_fallback: boolean
}
