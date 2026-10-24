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
