import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import indexHtml from '../../index.html?raw'
import {
  DEFAULT_SEARCH_FORM,
  FORM_STORAGE_KEY,
  THEME_STORAGE_KEY,
  getInitialTheme,
  loadSearchForm,
  normalizeSearchForm,
  resetSavedSettings,
  saveSearchForm,
} from './storage'

describe('search form storage', () => {
  beforeEach(() => localStorage.clear())

  it('adds the official-brand filter default to legacy saved forms', () => {
    localStorage.setItem(
      FORM_STORAGE_KEY,
      JSON.stringify({ brand: 'Nike', size: '26.5' }),
    )

    expect(loadSearchForm()).toMatchObject({
      brand: 'Nike',
      size: '26.5',
      officialBrandsOnly: false,
    })
  })

  it('persists the official-brand filter', () => {
    saveSearchForm({
      ...DEFAULT_SEARCH_FORM,
      officialBrandsOnly: true,
    })

    expect(loadSearchForm().officialBrandsOnly).toBe(true)
  })

  it('replaces each malformed field with its default and keeps the rest', () => {
    localStorage.setItem(
      FORM_STORAGE_KEY,
      JSON.stringify({
        brand: null,
        size: { cm: 26 },
        gender: 'kids',
        depth: 'all',
        maxPrice: '-5',
        pace: 'turbo',
        kids: 'yes',
        officialBrandsOnly: true,
      }),
    )

    const form = loadSearchForm()

    expect(form).toEqual({ ...DEFAULT_SEARCH_FORM, officialBrandsOnly: true })
    // Именно на этом раньше падала отрисовка формы.
    expect(() => form.brand.trim()).not.toThrow()
  })

  it('keeps numeric legacy values as strings', () => {
    expect(
      normalizeSearchForm({ size: 26.5, depth: 120, maxPrice: 15000 }),
    ).toMatchObject({ size: '26.5', depth: '120', maxPrice: '15000' })
  })

  it('keeps only the depths the select can show', () => {
    const cases: [unknown, string][] = [
      ['40', '40'],
      ['120', '120'],
      ['0', '0'],
      [' 120 ', '120'],
      [0, '0'],
      // Список показал бы «40 моделей», а '00' ушёл бы в поиск как 0 —
      // весь каталог без предупреждения.
      ['00', '40'],
      ['500', '40'],
      [500, '40'],
      ['', '40'],
      [null, '40'],
    ]
    for (const [saved, expected] of cases) {
      expect(normalizeSearchForm({ depth: saved }).depth, String(saved)).toBe(
        expected,
      )
    }
  })

  it('falls back to defaults for non-object or broken JSON', () => {
    for (const raw of ['[1,2]', '"text"', '42', '{broken']) {
      localStorage.setItem(FORM_STORAGE_KEY, raw)
      expect(loadSearchForm()).toEqual(DEFAULT_SEARCH_FORM)
    }
  })

  it('resets saved form and theme', () => {
    saveSearchForm({ ...DEFAULT_SEARCH_FORM, brand: 'Nike' })
    localStorage.setItem(THEME_STORAGE_KEY, 'dark')

    resetSavedSettings()

    expect(localStorage.getItem(FORM_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
    expect(loadSearchForm()).toEqual(DEFAULT_SEARCH_FORM)
  })
})

/** Тема, которую ставит встроенный скрипт index.html до загрузки React. */
function themeFromInlineScript(): string | undefined {
  const script = /<script>([\s\S]*?)<\/script>/.exec(indexHtml)?.[1]
  if (!script) throw new Error('в index.html нет встроенного скрипта темы')
  const root = document.documentElement
  delete root.dataset.theme
  root.classList.remove('dark')
  new Function(script)()
  expect(root.classList.contains('dark')).toBe(root.dataset.theme === 'dark')
  return root.dataset.theme
}

function mockSystemTheme(dark: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: dark && query === '(prefers-color-scheme: dark)',
    media: query,
  }))
}

describe('initial theme', () => {
  beforeEach(() => localStorage.clear())

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('paints the page with the theme the toggle starts from', () => {
    for (const systemDark of [false, true]) {
      mockSystemTheme(systemDark)
      for (const saved of [null, 'dark', 'light', 'auto', '']) {
        localStorage.clear()
        if (saved !== null) localStorage.setItem(THEME_STORAGE_KEY, saved)
        expect(
          themeFromInlineScript(),
          `сохранено ${saved}, тёмная система: ${systemDark}`,
        ).toBe(getInitialTheme())
      }
    }
  })

  it('follows the system for unknown values and blocked storage', () => {
    mockSystemTheme(true)
    localStorage.setItem(THEME_STORAGE_KEY, 'auto')
    expect(getInitialTheme()).toBe('dark')
    expect(themeFromInlineScript()).toBe('dark')

    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('хранилище заблокировано')
    })
    expect(getInitialTheme()).toBe('dark')
    expect(themeFromInlineScript()).toBe('dark')
  })
})
