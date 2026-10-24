// Piezas compartidas de la app de analítica: filtro de periodo, nombres de mes, CSV,
// variaciones frente al periodo anterior y catálogo de líneas de servicio.
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router'
import { api } from '../lib/api'
import { fmtMoney } from '../lib/format'
import type { Page } from '../lib/types'
import type { TargetMetric } from './types'

export const PERIODS = [
  { months: 3, label: '3 meses' },
  { months: 6, label: '6 meses' },
  { months: 12, label: '12 meses' },
  { months: 24, label: '24 meses' },
]

export function usePeriod(): [number, (months: number) => void] {
  const [params, setParams] = useSearchParams()
  const months = Number(params.get('months') ?? 12)
  const set = (m: number) => {
    const next = new URLSearchParams(params)
    next.set('months', String(m))
    setParams(next, { replace: true })
  }
  return [PERIODS.some((p) => p.months === months) ? months : 12, set]
}

export function PeriodPicker({ months, onChange }: { months: number; onChange: (m: number) => void }) {
  return (
    <div className="segmented" role="radiogroup" aria-label="Periodo">
      {PERIODS.map((p) => (
        <label key={p.months} className={p.months === months ? 'on' : ''}>
          <input type="radio" name="period" checked={p.months === months} onChange={() => onChange(p.months)} />
          {p.label}
        </label>
      ))}
    </div>
  )
}

const monthFmt = new Intl.DateTimeFormat('es-ES', { month: 'short', year: '2-digit', timeZone: 'UTC' })

/** «2026-10» → «oct 26» */
export function monthLabel(key: string) {
  const [y, m] = key.split('-').map(Number)
  return monthFmt.format(new Date(Date.UTC(y, m - 1, 1)))
}

export function pct(value: number | null | undefined) {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)} %`
}

/** Descarga filas como CSV (separador «;» y BOM para que Excel en español lo abra bien). */
export function downloadCsv(name: string, header: string[], rows: (string | number | null)[][]) {
  const esc = (v: string | number | null) => {
    const s = v === null ? '' : String(v)
    return /[";\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const text = '﻿' + [header, ...rows].map((r) => r.map(esc).join(';')).join('\r\n')
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/** Variación frente al periodo anterior. ``kind`` decide cómo se expresa:
 *  porcentaje de cambio (cifras) o puntos (tasas). */
export function Delta({
  now,
  before,
  kind = 'relative',
}: {
  now: number | null | undefined
  before: number | null | undefined
  kind?: 'relative' | 'points'
}) {
  if (now === null || now === undefined || before === null || before === undefined) return null
  let text: string
  let diff: number
  if (kind === 'points') {
    diff = Math.round((now - before) * 100)
    text = `${diff > 0 ? '+' : ''}${diff} p.`
  } else {
    if (before === 0) return now === 0 ? <span className="delta delta-flat">= </span> : <span className="delta delta-up">nuevo </span>
    diff = Math.round(((now - before) / Math.abs(before)) * 100)
    // Con una base muy pequeña el porcentaje se dispara: mejor «×N»
    text = diff >= 200 ? `×${(now / before).toLocaleString('es-ES', { maximumFractionDigits: 1 })}` : `${diff > 0 ? '+' : ''}${diff} %`
  }
  const tone = diff > 0 ? 'up' : diff < 0 ? 'down' : 'flat'
  const arrow = diff > 0 ? '▲' : diff < 0 ? '▼' : '='
  return (
    <span className={`delta delta-${tone}`}>
      <span aria-hidden="true">{arrow}</span> {text}{' '}
    </span>
  )
}

export const TARGET_METRICS: Record<TargetMetric, string> = {
  new_count: 'Oportunidades nuevas',
  new_eur: 'Importe nuevo',
  won_count: 'Oportunidades ganadas',
  won_eur: 'Importe ganado',
}

export const isMoneyMetric = (m: TargetMetric) => m.endsWith('_eur')

export function fmtMetric(metric: TargetMetric, value: string | number) {
  return isMoneyMetric(metric) ? fmtMoney(value) : Number(value).toLocaleString('es-ES')
}

export type ServiceLine = { code: string; name: string }

/** Líneas de servicio activas (código → nombre), para filtros y formularios. */
export function useServiceLines() {
  const query = useQuery({
    queryKey: ['analytics', 'service-lines'],
    queryFn: () => api<Page<ServiceLine>>('/api/analytics/service-lines', { query: { per_page: 100 } }),
    staleTime: 5 * 60_000,
  })
  const lines = query.data?.items ?? []
  const names = Object.fromEntries(lines.map((l) => [l.code, l.name])) as Record<string, string>
  return { lines, names }
}
