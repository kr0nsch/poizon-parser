import { beforeEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_SEARCH_FORM,
  FORM_STORAGE_KEY,
  loadSearchForm,
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
})
