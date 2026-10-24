// Textos y formatos de la app de administración.
import type { Budget } from './types'

const usdFmt = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
const usdFine = new Intl.NumberFormat('es-ES', { style: 'currency', currency: 'USD', maximumFractionDigits: 4 })

/** Precios del proveedor: en dólares, como los publica. */
export function usd(value: string | number | null | undefined, fine = false): string {
  if (value === null || value === undefined || value === '') return '—'
  return (fine ? usdFine : usdFmt).format(Number(value))
}

/** Gasto y límites de IA: se guardan en USD y se muestran en euros. */
export { fmtAiCost as eur } from '../lib/format'

export const BUDGET_SCOPE: Record<Budget['scope'], string> = {
  global: 'Toda la plataforma',
  service: 'Tipo de tarea',
  user: 'Por persona',
}

/** Un presupuesto «por persona» sin id se aplica a cada usuario por separado. */
export function perPerson(b: Budget) {
  return b.scope === 'user' && !b.scope_id
}

export const COMPLIANCE_EVENTS: Record<string, string> = {
  AI_REQUEST_BLOCKED: 'Peticiones bloqueadas por los guardarraíles',
  AI_OUTPUT_BLOCKED: 'Respuestas bloqueadas',
  AI_BUDGET_EXCEEDED: 'Presupuesto superado',
  PII_DETECTED_IN_OUTPUT: 'Datos personales en respuestas',
  PROMPT_INTEGRITY_VIOLATION: 'Prompts modificados fuera de Admin',
}

export const APP_NAMES: Record<string, string> = {
  operations: 'Operaciones',
  analytics: 'Analítica',
  admin: 'Administración',
  security: 'Seguridad',
}

export const MODULE_NAMES: Record<string, string> = {
  clients: 'Clientes',
  opportunities: 'Oportunidades',
  documents: 'Documentos',
  proposals: 'Propuestas',
  templates: 'Plantillas',
  portfolio: 'Portfolio de servicios',
  talent: 'Talento',
  alerts: 'Alertas',
  notifications: 'Avisos',
  copilot: 'Copiloto',
  reports: 'Informes',
  dashboards: 'Cuadros de mando',
  competitors: 'Competidores',
  users: 'Usuarios',
  roles: 'Roles',
  llm_config: 'Modelos y costes de IA',
  prompts: 'Prompts',
  audit: 'Auditoría',
  health: 'Estado',
  tasks: 'Tareas',
  search: 'Búsqueda',
  agents: 'Agentes',
  guardrails: 'Guardarraíles',
}

export const ACTION_NAMES: Record<string, string> = {
  read: 'ver',
  write: 'editar',
  delete: 'borrar',
  manage: 'gestionar',
  export: 'exportar',
  upload: 'subir',
  approve: 'aprobar',
  send: 'enviar',
  generate: 'generar',
}

export const AI_MODULE_NAMES: Record<string, string> = {
  document_analyzer: 'Análisis de documentos',
  proposal_generator: 'Redacción de propuestas',
  cv_analyzer: 'Análisis de CV',
  copilot_chat: 'Copiloto',
  analytics_assistant: 'Preguntas sobre los datos (Analítica)',
}

export const SEVERITY_TONE: Record<string, 'neutral' | 'warning' | 'danger'> = {
  INFO: 'neutral',
  WARNING: 'warning',
  ERROR: 'danger',
  CRITICAL: 'danger',
}

export const APPROVAL_LEVELS: Record<string, string> = {
  auto: 'Sin preguntar',
  notify: 'Avisando',
  approve: 'Pidiendo aprobación',
}

export const AGENT_STATUS: Record<string, string> = { draft: 'Borrador', active: 'Activo', archived: 'Archivado' }

export const INTENTS: Record<string, string> = {
  CHAT_RAG: 'Pregunta a documentos',
  AGENT_TOOLS: 'Consulta con herramientas',
  WORKFLOW: 'Flujo de trabajo',
  OFF_TOPIC: 'Fuera de tema',
}
