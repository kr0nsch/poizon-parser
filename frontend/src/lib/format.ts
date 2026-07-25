import type { SearchMatch } from '../api/types'

export function formatNumber(value: number | null | undefined): string {
  if (value == null) return '—'
  return new Intl.NumberFormat('ru-RU', {
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatMoney(
  match: Pick<SearchMatch, 'price' | 'price_text'>,
): string {
  if (match.price_text) return match.price_text
  if (match.price == null) return 'Цена не указана'
  return `${new Intl.NumberFormat('ru-RU').format(match.price)} ₽`
}

function formatSizeValue(value: string | number): string {
  const parsed =
    typeof value === 'number' ? value : Number(value.trim().replace(',', '.'))
  return Number.isFinite(parsed) ? formatNumber(parsed) : String(value)
}

export function thumbnailUrl(
  url: string | null | undefined,
): string | undefined {
  if (!url) return undefined
  if (url.includes('x-oss-process') || url.endsWith('.svg')) return url
  const separator = url.includes('?') ? '&' : '?'
  return `${url}${separator}x-oss-process=image/resize,s_480/format,webp`
}

export function poizonSizeLabel(match: SearchMatch): string {
  const sizes = Object.entries(match.sizes ?? {})
    .filter(([, value]) => value != null && value !== '')
    .map(([scale, value]) => `${scale} ${formatSizeValue(value)}`)

  if (sizes.length > 0) return sizes.join(' / ')
  if (match.size != null) {
    return `${formatSizeValue(match.size)} ${match.matched_scale ?? ''}`.trim()
  }
  return 'Размер не указан'
}

export function fitHint(tip: string | null | undefined): string | undefined {
  if (!tip) return undefined
  const found = /([+-]\s*\d+(?:[.,]\d+)?)/.exec(tip)
  return found?.[1]?.replace(/\s/g, '')
}

export function deliveryDays(value: string | null | undefined): number {
  const found = /(\d+)/.exec(value ?? '')
  return found ? Number(found[1]) : Number.POSITIVE_INFINITY
}

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return ''
  if (seconds < 60) return `${Math.round(seconds)} с`
  return `${Math.round(seconds / 60)} мин`
}

export function formatActivityAge(seconds: number): string {
  if (seconds < 2) return 'только что'
  return `${Math.round(seconds)} с назад`
}

export function slugify(value: string): string {
  const slug = value
    .trim()
    .toLocaleLowerCase('ru-RU')
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
  return slug || 'poizon'
}
