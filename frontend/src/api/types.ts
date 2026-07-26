export type Gender = 'men' | 'women'

export type SearchPace = 'polite' | 'normal' | 'fast'

export type SizeScale = 'EU' | 'RU' | 'UK' | 'US M' | 'US W' | 'CM' | 'MM'

export interface Brand {
  has_official_size_chart: boolean
  id: number
  name: string
  size_chart_brand: string | null
  size_chart_source: string | null
  slug: string
  url: string
}

export interface BrandsResponse {
  brands: Brand[]
}

export interface SizeConversion {
  brand: string
  gender: Gender
  requested_foot: number
  exact: boolean
  eu?: number
  us?: number
  uk?: number
  cm?: number
  foot?: number
}

export interface ConversionRequest {
  foot: number
  brand?: string
  gender?: Gender
}

export interface ConversionResponse {
  sizes: SizeConversion | null
  compare: SizeConversion[]
  note?: string
}

export interface SearchRequest {
  brand: string
  size: string
  scale?: SizeScale
  depth?: number | null
  maxPrice?: number | null
  minPrice?: number | null
  pace?: SearchPace
  gender?: Gender
  kids?: boolean
}

export interface StartSearchResponse {
  id: string
}

export type ConversionSource =
  'native' | 'brand' | 'table' | 'standard' | 'fallback' | ''

export interface SearchMatch {
  spu_id: number
  sku_id: number
  title: string
  article: string
  brand: string
  url: string
  requested_size: number
  requested_scale: SizeScale
  converted_eu: number | null
  converted_cm: number | null
  converted_foot: number | null
  exact_conversion: boolean
  conversion_source: ConversionSource
  conversion_note: string
  matched_scale: SizeScale
  size: string
  sizes: Record<string, string>
  price: number | null
  price_text: string
  currency: string
  in_stock: boolean
  delivery: string
  variant: string
  inventory_no: string
  labels: string[]
  product_min_price: number | null
  size_tip: string
  image: string
}

export type SearchStatus =
  'running' | 'captcha' | 'done' | 'cancelled' | 'error'

export type SearchPhase = 'brand' | 'collect' | 'check'

export interface SearchJobBrand {
  id: number
  name: string
  url: string
}

export interface CaptchaChallenge {
  url: string | null
  reason: string | null
  since: number
}

export interface SearchStats {
  requests?: number
  cache_hits?: number
  cooldowns?: number
  challenges?: number
}

export interface SearchSnapshot {
  id: string
  status: SearchStatus
  phase: SearchPhase
  brand: SearchJobBrand | null
  collected: number
  checked: number
  total: number
  found: number
  matches: SearchMatch[]
  log: string[]
  error: string
  paused: boolean
  captcha: CaptchaChallenge | null
  cooldown_until: number
  prefiltered: number
  stats: SearchStats
  activity: string
  active_requests: number
  last_activity_at: number
  pause_requested: boolean
  stop_reason: string
  started_at: number
  finished_at: number | null
  idle_seconds: number
}

export type SearchJob = SearchSnapshot

export interface SearchActionResponse {
  ok: boolean
}

export interface PickQuery {
  brand: string
  size: number | string
  scale: SizeScale
}

export interface Pick {
  id: string
  saved_at: string
  query: PickQuery
  match: SearchMatch
}

export interface PicksResponse {
  items: Pick[]
}

export interface AddPickRequest {
  match: SearchMatch
  query: PickQuery
}

export interface AddPickResponse {
  item: Pick
  created: boolean
}

export interface ClearPicksResponse {
  removed: number
}

export interface ReportRequest {
  jobId?: string | null
  matches?: SearchMatch[]
  brand?: string
  size?: number | string
  scale?: SizeScale
  gender?: Gender
  embed?: boolean
}

export interface ReportResponse {
  dir: string
  file: string
  view: string
}

export interface HealthResponse {
  status: 'ok'
  jobs: {
    total: number
    active: number
  }
  brands_loaded: boolean
  picks: number
}

export const ACTIVE_SEARCH_STATUSES = ['running', 'captcha'] as const

export const TERMINAL_SEARCH_STATUSES = ['done', 'cancelled', 'error'] as const

export function isActiveSearchStatus(status: SearchStatus): boolean {
  return (ACTIVE_SEARCH_STATUSES as readonly SearchStatus[]).includes(status)
}

export function isTerminalSearchStatus(status: SearchStatus): boolean {
  return (TERMINAL_SEARCH_STATUSES as readonly SearchStatus[]).includes(status)
}
