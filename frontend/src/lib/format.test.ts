import { describe, expect, it } from 'vitest'
import { daysUntil, fmtAiCost, fmtBytes, fmtMoney, label, setUsdEurRate, usdToEur } from './format'

// Intl en español separa la cifra y el símbolo con un espacio duro
const plain = (s: string) => s.replace(/\s/g, ' ')

describe('formatos', () => {
  it('importes en euros sin decimales y guion si no hay dato', () => {
    expect(plain(fmtMoney('125000.40'))).toBe('125.000 €')
    expect(fmtMoney(null)).toBe('—')
    expect(fmtMoney('no-es-un-número')).toBe('—')
  })

  it('los costes de IA se guardan en dólares y se muestran en euros', () => {
    setUsdEurRate(0.5)
    expect(usdToEur(10)).toBe(5)
    expect(plain(fmtAiCost('2.00'))).toBe('1,00 €')
    expect(plain(fmtAiCost(0.0123, true))).toBe('0,0062 €')
    setUsdEurRate(0) // un cambio no válido no se aplica
    expect(usdToEur(10)).toBe(5)
    setUsdEurRate(0.92)
  })

  it('tamaños de fichero, días que faltan y etiquetas', () => {
    expect(fmtBytes(2048)).toBe('2 KB')
    expect(fmtBytes(3 * 1024 ** 2)).toBe('3.0 MB')
    expect(daysUntil(new Date(Date.now() + 2.5 * 86_400_000).toISOString())).toBe(3)
    expect(label({ won: 'Ganada' }, 'won')).toBe('Ganada')
  })
})
