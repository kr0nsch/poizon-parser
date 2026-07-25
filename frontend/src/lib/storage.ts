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
}

export const DEFAULT_SEARCH_FORM: StoredSearchForm = {
  brand: '',
  size: '',
  gender: 'men',
  depth: '40',
  maxPrice: '',
  pace: 'normal',
  kids: false,
}

export function loadSearchForm(): StoredSearchForm {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(FORM_STORAGE_KEY) ?? 'null',
    )
    if (!value || typeof value !== 'object') return DEFAULT_SEARCH_FORM
    const saved = value as Partial<StoredSearchForm>
    return {
      ...DEFAULT_SEARCH_FORM,
      ...Object.fromEntries(
        Object.keys(DEFAULT_SEARCH_FORM)
          .filter((key) => key in saved)
          .map((key) => [key, saved[key as keyof StoredSearchForm]]),
      ),
    } as StoredSearchForm
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

export function getInitialTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY)
    if (saved === 'dark' || saved === 'light') return saved
  } catch {
    // Follow the OS preference when storage is unavailable.
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches
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
