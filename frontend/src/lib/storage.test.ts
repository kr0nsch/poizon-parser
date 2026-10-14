import { beforeEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_SEARCH_FORM,
  FORM_STORAGE_KEY,
  THEME_STORAGE_KEY,
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
