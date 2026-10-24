// Formatos y textos en español para los valores que devuelve la API.

const dateFmt = new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'short', year: 'numeric' })
const dateTimeFmt = new Intl.DateTimeFormat('es-ES', {
  day: 'numeric',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
})
const moneyFmt = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 })
const relFmt = new Intl.RelativeTimeFormat('es-ES', { numeric: 'auto' })

export function fmtDate(iso: string | null | undefined): string {
  return iso ? dateFmt.format(new Date(iso)) : '—'
}

export function fmtDateTime(iso: string | null | undefined): string {
  return iso ? dateTimeFmt.format(new Date(iso)) : '—'
}

/** «hace 3 horas», «dentro de 5 días». */
export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diff = (new Date(iso).getTime() - Date.now()) / 1000
  const abs = Math.abs(diff)
  if (abs < 60) return relFmt.format(Math.round(diff), 'second')
  if (abs < 3600) return relFmt.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return relFmt.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 45) return relFmt.format(Math.round(diff / 86400), 'day')
  return fmtDate(iso)
}

/** Días que faltan hasta una fecha (negativo si ya pasó). */
export function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null
  return Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000)
}

export function fmtMoney(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—'
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? moneyFmt.format(n) : '—'
}

// Costes de IA: se guardan en dólares (lo que cobra el proveedor) y se muestran en
// euros al cambio de AI_USD_EUR_RATE, que llega con /api/auth/me.
let usdEurRate = 0.92
const aiCostFmt = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 })
const aiCostFine = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'EUR', maximumFractionDigits: 4 })

export function setUsdEurRate(rate: number | null | undefined): void {
  if (rate && rate > 0) usdEurRate = rate
}

export function usdToEur(usd: number): number {
  return usd * usdEurRate
}

export function eurToUsd(eur: number): number {
  return eur / usdEurRate
}

/** Coste de IA guardado en USD, mostrado en euros. */
export function fmtAiCost(usd: string | number | null | undefined, fine = false): string {
  if (usd === null || usd === undefined || usd === '') return '—'
  return (fine ? aiCostFine : aiCostFmt).format(usdToEur(Number(usd)))
}

export function fmtBytes(bytes: number | null | undefined): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

export function fmtScore(score: number | null | undefined): string {
  return score === null || score === undefined ? '—' : score.toLocaleString('es-ES', { maximumFractionDigits: 1 })
}

export const OPPORTUNITY_STATUS: Record<string, string> = {
  detected: 'Detectada',
  qualifying: 'En cualificación',
  qualified: 'Cualificada',
  analyzing: 'En análisis',
  go_no_go: 'Decisión GO/NO-GO',
  preparing_proposal: 'Preparando propuesta',
  proposal_review: 'Propuesta en revisión',
  proposal_sent: 'Propuesta enviada',
  negotiation: 'Negociación',
  won: 'Ganada',
  lost: 'Perdida',
  discarded: 'Descartada',
}

export const SECTORS: Record<string, string> = {
  public: 'Sector público',
  health: 'Sanidad',
  finance: 'Banca y seguros',
  energy: 'Energía',
  industry: 'Industria',
  retail: 'Comercio',
  telecom: 'Telecomunicaciones',
  education: 'Educación',
  other: 'Otro',
}

export const PHASES: Record<string, string> = {
  F1: 'F1 · Detección',
  F2: 'F2 · Cualificación',
  F3: 'F3 · Decisión',
  F4: 'F4 · Propuesta',
  F5: 'F5 · Cierre',
}

export const PROPOSAL_STATUS: Record<string, string> = {
  draft: 'Borrador',
  in_review: 'En revisión',
  approved: 'Aprobada',
  sent: 'Enviada',
  won: 'Ganada',
  lost: 'Perdida',
  archived: 'Archivada',
}

export const PROPOSAL_TYPES: Record<string, string> = {
  base: 'Base',
  competitive: 'Competitiva',
  premium: 'Premium',
  custom: 'A medida',
  executive: 'Ejecutiva',
}

export const REVIEW_KINDS: Record<string, string> = {
  technical: 'Técnica',
  executive: 'Ejecutiva',
  area: 'De área',
  general: 'General',
  any: 'Cualquiera',
}

export const GENERATION_STATUS: Record<string, string> = {
  idle: 'Sin redactar',
  queued: 'En cola',
  running: 'Redactando…',
  done: 'Redactada',
  failed: 'Falló',
}

export const DOC_STATUS: Record<string, string> = {
  pending: 'Pendiente',
  processing: 'Procesando',
  processed: 'Procesado',
  failed: 'Fallido',
}

export const INDEX_STATUS: Record<string, string> = {
  none: 'Sin indexar',
  pending: 'Indexando',
  indexed: 'Indexado',
  failed: 'Fallo al indexar',
  skipped: 'No indexable',
}

export const DOC_LINK_ROLES: Record<string, string> = {
  requirements: 'Pliego / requisitos',
  annex: 'Anexo',
  budget: 'Presupuesto',
  other: 'Otro',
}

export const VERDICTS: Record<string, string> = { GO: 'GO', NO_GO: 'NO-GO', CONDITIONAL: 'Condicionado' }

export const MEETS: Record<string, string> = { yes: 'Cumple', partial: 'Parcial', no: 'No cumple', unknown: 'Sin datos' }

export const SEVERITY: Record<string, string> = { low: 'Baja', medium: 'Media', high: 'Alta', critical: 'Crítica' }

export const FAMILIES: Record<string, string> = {
  cloud: 'Cloud',
  cyber: 'Ciberseguridad',
  applications: 'Aplicaciones',
  data: 'Datos',
  infrastructure: 'Infraestructura',
  management: 'Gestión',
  consulting: 'Consultoría',
}

export const SENIORITY: Record<string, string> = {
  JUNIOR: 'Junior',
  MID: 'Intermedio',
  SENIOR: 'Senior',
  LEAD: 'Lead',
  PRINCIPAL: 'Principal',
  DIRECTOR: 'Director/a',
}

export const MEMORY_CATEGORIES: Record<string, string> = {
  preference: 'Preferencia',
  client_fact: 'Dato de cliente',
  workflow: 'Forma de trabajar',
  insight: 'Conclusión',
}

export const TOOL_NAMES: Record<string, string> = {
  search_opportunities: 'Buscar oportunidades',
  get_opportunity: 'Ver oportunidad',
  search_documents: 'Buscar en documentos',
  get_document: 'Ver documento',
  search_clients: 'Buscar clientes',
  search_profiles: 'Buscar perfiles',
  get_proposal: 'Ver propuesta',
  list_proposal_templates: 'Ver plantillas',
  analyze_opportunity: 'Analizar oportunidad',
  analyze_document: 'Analizar documento',
  create_proposal: 'Crear propuesta',
  generate_proposal: 'Redactar propuesta',
  generate_cv: 'CV a medida',
  export_proposal: 'Generar paquete',
}

export function label(map: Record<string, string>, key: string | null | undefined): string {
  if (!key) return '—'
  return map[key] ?? key
}
