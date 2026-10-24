import {
  DOC_STATUS,
  GENERATION_STATUS,
  INDEX_STATUS,
  OPPORTUNITY_STATUS,
  PROPOSAL_STATUS,
  VERDICTS,
  label,
} from '../lib/format'
import { Badge, type Tone } from './ui'

const OPP_TONE: Record<string, Tone> = {
  detected: 'neutral',
  qualifying: 'info',
  qualified: 'info',
  analyzing: 'info',
  go_no_go: 'warning',
  preparing_proposal: 'accent',
  proposal_review: 'accent',
  proposal_sent: 'accent',
  negotiation: 'warning',
  won: 'success',
  lost: 'danger',
  discarded: 'neutral',
}

const PROPOSAL_TONE: Record<string, Tone> = {
  draft: 'neutral',
  in_review: 'warning',
  approved: 'success',
  sent: 'accent',
  won: 'success',
  lost: 'danger',
  archived: 'neutral',
}

const DOC_TONE: Record<string, Tone> = { pending: 'neutral', processing: 'info', processed: 'success', failed: 'danger' }
const GEN_TONE: Record<string, Tone> = { idle: 'neutral', queued: 'info', running: 'info', done: 'success', failed: 'danger' }
const VERDICT_TONE: Record<string, Tone> = { GO: 'success', NO_GO: 'danger', CONDITIONAL: 'warning' }

export function OpportunityStatus({ status }: { status: string }) {
  return <Badge tone={OPP_TONE[status] ?? 'neutral'}>{label(OPPORTUNITY_STATUS, status)}</Badge>
}

export function ProposalStatus({ status }: { status: string }) {
  return <Badge tone={PROPOSAL_TONE[status] ?? 'neutral'}>{label(PROPOSAL_STATUS, status)}</Badge>
}

export function DocumentStatus({ status }: { status: string }) {
  return <Badge tone={DOC_TONE[status] ?? 'neutral'}>{label(DOC_STATUS, status)}</Badge>
}

export function IndexStatus({ status }: { status: string }) {
  return <Badge tone={status === 'indexed' ? 'success' : status === 'failed' ? 'danger' : 'neutral'}>{label(INDEX_STATUS, status)}</Badge>
}

export function GenerationStatus({ status }: { status: string }) {
  return <Badge tone={GEN_TONE[status] ?? 'neutral'}>{label(GENERATION_STATUS, status)}</Badge>
}

export function Verdict({ verdict }: { verdict: string | null | undefined }) {
  if (!verdict) return null
  return <Badge tone={VERDICT_TONE[verdict] ?? 'neutral'}>{label(VERDICTS, verdict)}</Badge>
}
