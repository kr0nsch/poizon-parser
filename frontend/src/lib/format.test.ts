import { describe, expect, it } from 'vitest'

import type { SearchMatch } from '../api'
import {
  deliveryDays,
  fitHint,
  formatMoney,
  formatQuerySize,
  formatSize,
  poizonSizeLabel,
  slugify,
  thumbnailUrl,
} from './format'

const baseMatch = {
  price: 12_490,
  price_text: '',
  sizes: { EU: '42', CM: '26.5' },
  size: '42',
  matched_scale: 'EU',
} as unknown as SearchMatch

describe('format helpers', () => {
  it('formats price and available POIZON size scales', () => {
    expect(formatMoney(baseMatch)).toContain('12')
    expect(formatMoney(baseMatch)).toContain('₽')
    expect(poizonSizeLabel(baseMatch)).toBe('EU 42 / CM 26,5')
    expect(
      poizonSizeLabel({
        ...baseMatch,
        sizes: { EU: '42,5' },
      }),
    ).toBe('EU 42,5')
  })

  it('formats shoe sizes with thirds like Adidas labels', () => {
    expect(formatSize(43 + 1 / 3)).toBe('43⅓')
    expect(formatSize(42.6667)).toBe('42⅔')
    expect(formatSize(42.5)).toBe('42,5')
    expect(formatSize(42)).toBe('42')
    expect(formatSize(null)).toBe('—')
  })

  it('describes the saved query in Russian number format', () => {
    expect(formatQuerySize('26.5', 'CM')).toBe('стопа 26,5 см')
    expect(formatQuerySize(26.5, 'cm')).toBe('стопа 26,5 см')
    expect(formatQuerySize(265, 'MM')).toBe('стопа 265 мм')
    expect(formatQuerySize('42', 'EU')).toBe('EU 42')
    expect(formatQuerySize('7', 'US W')).toBe('US W 7')
    expect(formatQuerySize('', 'EU')).toBe('')
  })

  it('extracts delivery and fit values', () => {
    expect(deliveryDays('доставка 7–10 дней')).toBe(7)
    expect(deliveryDays('нет данных')).toBe(Number.POSITIVE_INFINITY)
    expect(fitHint('маломерит на + 0,5')).toBe('+0,5')
  })

  it('builds stable filenames and image resize URLs', () => {
    expect(slugify('New Balance  ')).toBe('new-balance')
    expect(thumbnailUrl('https://img.test/shoe.jpg')).toContain('resize,s_480')
    expect(thumbnailUrl('https://img.test/shoe.svg')).toBe(
      'https://img.test/shoe.svg',
    )
  })
})
