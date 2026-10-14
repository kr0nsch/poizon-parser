export const FORM_STORAGE_KEY = 'poizon-form'
export const THEME_STORAGE_KEY = 'poizon-theme'

export type Theme = 'light' | 'dark'

export interface StoredSearchForm {
  brand: string
  size: string
  gender: 'men' | 'women'
  depth: string
  maxPrice: string
  pace: 'polite' | 'normal' | 'fast'
  kids: boolean
  officialBrandsOnly: boolean
}

export const DEFAULT_SEARCH_FORM: StoredSearchForm = {
  brand: '',
  size: '',
  gender: 'men',
  depth: '40',
  maxPrice: '',
  pace: 'normal',
  kids: false,
  officialBrandsOnly: false,
}

const GENDERS: readonly StoredSearchForm['gender'][] = ['men', 'women']
const PACES: readonly StoredSearchForm['pace'][] = ['polite', 'normal', 'fast']

function oneOf<T extends string>(
  value: unknown,
  options: readonly T[],
  fallback: T,
): T {
  return (options as readonly unknown[]).includes(value)
    ? (value as T)
    : fallback
}

function text(value: unknown, fallback: string): string {
  if (typeof value === 'string') return value
  // Число в поле ввода — безобидная старая запись, его можно сохранить.
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  return fallback
}

function digits(value: unknown, fallback: string): string {
  const raw = text(value, fallback).trim()
  // Мусор в глубине превращался в 0, а это «весь каталог» — долгий поиск.
  return /^\d+$/.test(raw) ? raw : fallback
}

function price(value: unknown, fallback: string): string {
  const raw = text(value, fallback).trim()
  if (raw === '') return ''
  const amount = Number(raw)
  return Number.isFinite(amount) && amount >= 0 ? raw : fallback
}

function flag(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

/**
 * Приводит сохранённую форму к ожидаемым типам. localStorage может хранить
 * что угодно (старые версии, ручные правки), а форма вызывает строковые
 * методы прямо при отрисовке — поэтому каждое поле проверяется отдельно, и
 * негодное заменяется значением по умолчанию, не трогая остальные.
 */
export function normalizeSearchForm(value: unknown): StoredSearchForm {
  const saved: Record<string, unknown> =
    value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : {}
  const defaults = DEFAULT_SEARCH_FORM

  return {
    brand: text(saved.brand, defaults.brand),
    size: text(saved.size, defaults.size),
    gender: oneOf(saved.gender, GENDERS, defaults.gender),
    depth: digits(saved.depth, defaults.depth),
    maxPrice: price(saved.maxPrice, defaults.maxPrice),
    pace: oneOf(saved.pace, PACES, defaults.pace),
    kids: flag(saved.kids, defaults.kids),
    officialBrandsOnly: flag(
      saved.officialBrandsOnly,
      defaults.officialBrandsOnly,
    ),
  }
}

export function loadSearchForm(): StoredSearchForm {
  try {
    return normalizeSearchForm(
      JSON.parse(localStorage.getItem(FORM_STORAGE_KEY) ?? 'null'),
    )
  } catch {
    return DEFAULT_SEARCH_FORM
  }
}

export function saveSearchForm(form: StoredSearchForm): void {
  try {
    localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form))
  } catch {
    // Private mode or a storage quota should not block the search itself.
  }
}

/** Забывает сохранённые форму и тему (итоги живут на сервере и не страдают). */
export function resetSavedSettings(): void {
  for (const key of [FORM_STORAGE_KEY, THEME_STORAGE_KEY]) {
    try {
      localStorage.removeItem(key)
    } catch {
      // Недоступное хранилище и так ничего не помнит.
    }
  }
}

export function getInitialTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    // Follow the OS preference when storage is unavailable.
  }
  return typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark')
  document.documentElement.dataset.theme = theme
  document.documentElement.style.colorScheme = theme
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Theme switching should still work in private/restricted storage modes.
  }
}
