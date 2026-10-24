// Piezas compartidas de la app de analítica: filtro de periodo, nombres de mes y CSV.
import { useSearchParams } from 'react-router'

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
