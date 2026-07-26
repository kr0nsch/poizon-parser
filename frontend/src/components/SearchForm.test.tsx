import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Brand } from '../api/types'
import { DEFAULT_SEARCH_FORM } from '../lib/storage'
import { SearchForm } from './SearchForm'

const brands: Brand[] = [
  {
    has_official_size_chart: true,
    id: 1,
    name: 'Nike',
    size_chart_brand: 'Nike',
    size_chart_source: 'https://nike.example/size-guide',
    slug: 'nike',
    url: '/nike',
  },
  {
    has_official_size_chart: false,
    id: 2,
    name: 'Puma',
    size_chart_brand: null,
    size_chart_source: null,
    slug: 'puma',
    url: '/puma',
  },
]

describe('SearchForm', () => {
  it('submits valid brand and foot length and exposes measuring help', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const onSubmit = vi.fn()

    render(
      <SearchForm
        active={false}
        brands={brands}
        brandsLoading={false}
        conversionLoading={false}
        form={{ ...DEFAULT_SEARCH_FORM, brand: 'Nike', size: '26.5' }}
        onCancel={vi.fn()}
        onChange={onChange}
        onSubmit={onSubmit}
        starting={false}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Как измерить' }))
    expect(screen.getByText('Как измерить стопу')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Найти' }))
    expect(onSubmit).toHaveBeenCalledOnce()
    expect(onChange).not.toHaveBeenCalled()
  })

  it('shows the long-catalog warning', () => {
    render(
      <SearchForm
        active={false}
        brands={[]}
        brandsLoading={false}
        conversionLoading={false}
        form={{ ...DEFAULT_SEARCH_FORM, depth: '0' }}
        onCancel={vi.fn()}
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        starting={false}
      />,
    )

    expect(screen.getByText(/может занять десятки минут/i)).toBeInTheDocument()
  })

  it('filters suggestions to official charts without clearing the brand', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const onSubmit = vi.fn()
    const brandsWithDuplicate = [
      ...brands,
      {
        ...brands[0]!,
        id: 3,
        slug: 'nike-duplicate',
        url: '/nike-duplicate',
      },
    ]
    const form = {
      ...DEFAULT_SEARCH_FORM,
      brand: 'Puma',
      size: '26.5',
    }
    const props = {
      active: false,
      brands: brandsWithDuplicate,
      brandsLoading: false,
      conversionLoading: false,
      onCancel: vi.fn(),
      onChange,
      onSubmit,
      starting: false,
    }
    const { container, rerender } = render(
      <SearchForm {...props} form={form} />,
    )

    const optionValues = () =>
      Array.from(
        container.querySelectorAll<HTMLOptionElement>('#brand-options option'),
      ).map((option) => option.value)

    expect(optionValues()).toEqual(['Nike', 'Puma', 'Nike'])

    await user.click(
      screen.getByRole('switch', {
        name: 'Только бренды с официальной размерной сеткой',
      }),
    )
    expect(onChange).toHaveBeenLastCalledWith({
      ...form,
      officialBrandsOnly: true,
    })

    rerender(
      <SearchForm {...props} form={{ ...form, officialBrandsOnly: true }} />,
    )

    expect(optionValues()).toEqual(['Nike'])
    expect(screen.getByLabelText(/^Бренд/)).toHaveValue('Puma')
    expect(screen.getByText(/«Puma» остаётся выбранным/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Найти' }))
    expect(onSubmit).toHaveBeenCalledOnce()
  })
})
