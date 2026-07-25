import { describe, expect, it } from 'vitest'

import type { SearchMatch } from '../api'
import {
  deliveryDays,
  fitHint,
  formatMoney,
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
