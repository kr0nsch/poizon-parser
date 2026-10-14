import { render, screen, waitFor } from '@testing-library/react'
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

  it('shows the official foot length and selected grid for New Balance', () => {
    render(
      <SearchForm
        active={false}
        brands={brands}
        brandsLoading={false}
        conversion={{
          sizes: {
            brand: 'New Balance',
            gender: 'women',
            requested_foot: 26.5,
            exact: true,
            eu: 41,
            us: 9.5,
            uk: 7.5,
            cm: 26.5,
            foot: 26.5,
          },
          compare: [],
        }}
        conversionLoading={false}
        form={{
          ...DEFAULT_SEARCH_FORM,
          brand: 'New Balance',
          gender: 'women',
          size: '26.5',
        }}
        onCancel={vi.fn()}
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        starting={false}
      />,
    )

    expect(
      screen.getByText(/Ваш размер в New Balance \(женская сетка\)/),
    ).toBeInTheDocument()
    expect(screen.getByText(/стопа 26,5 см/)).toBeInTheDocument()
    expect(screen.queryByText(/ярлык/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/приблизительно/i)).not.toBeInTheDocument()
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
    expect(
      screen.getByText(/«Puma» остаётся выбранным/i, {
        selector: '.official-brand-filter__notice',
      }),
    ).toBeInTheDocument()
    expect(
      screen
        .getAllByRole('status')
        .some((region) =>
          region.textContent?.startsWith('«Puma» остаётся выбранным'),
        ),
    ).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Найти' }))
    expect(onSubmit).toHaveBeenCalledOnce()
  })

  it('announces the converted size through a persistent live region', () => {
    const props = {
      active: false,
      brands,
      brandsLoading: false,
      form: { ...DEFAULT_SEARCH_FORM, brand: 'Nike', size: '26.5' },
      onCancel: vi.fn(),
      onChange: vi.fn(),
      onSubmit: vi.fn(),
      starting: false,
    }
    const { rerender } = render(<SearchForm {...props} conversionLoading />)
    const regions = screen.getAllByRole('status')
    expect(regions.every((region) => region.textContent === '')).toBe(true)

    rerender(
      <SearchForm
        {...props}
        conversionLoading={false}
        conversion={{
          sizes: {
            brand: 'Nike',
            gender: 'men',
            requested_foot: 26.5,
            exact: false,
            eu: 42,
            us: 8.5,
            uk: 7.5,
            cm: 26.5,
          },
          compare: [],
        }}
      />,
    )

    // Те же узлы, что и до ответа: меняется только их текст.
    expect(screen.getAllByRole('status')).toEqual(regions)
    expect(regions.map((region) => region.textContent).filter(Boolean)).toEqual(
      ['Ваш размер в Nike: EU 42, US 8,5, UK 7,5, приблизительно'],
    )
  })

  it('asks for a brand instead of quoting an empty one', () => {
    render(
      <SearchForm
        active={false}
        brands={brands}
        brandsLoading={false}
        conversion={{
          sizes: null,
          compare: [
            {
              brand: 'Nike',
              gender: 'men',
              requested_foot: 26.5,
              exact: true,
              eu: 42,
            },
            {
              brand: 'adidas',
              gender: 'men',
              requested_foot: 26.5,
              exact: true,
              eu: 42.5,
            },
          ],
        }}
        conversionLoading={false}
        form={{ ...DEFAULT_SEARCH_FORM, brand: '  ', size: '26.5' }}
        onCancel={vi.fn()}
        onChange={vi.fn()}
        onSubmit={vi.fn()}
        starting={false}
      />,
    )

    expect(screen.queryByText(/«\s*»/)).not.toBeInTheDocument()
    expect(
      screen.getByText(
        'Укажите бренд, чтобы перевести размер по его таблице.',
        {
          selector: '.size-preview span',
        },
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('adidas EU 42,5')).toBeInTheDocument()
  })

  it('returns focus to «Найти» when «Стоп» disappears', async () => {
    const props = {
      brands,
      brandsLoading: false,
      conversionLoading: false,
      form: { ...DEFAULT_SEARCH_FORM, brand: 'Nike', size: '26.5' },
      onCancel: vi.fn(),
      onChange: vi.fn(),
      onSubmit: vi.fn(),
      starting: false,
    }
    const { rerender } = render(<SearchForm {...props} active />)
    screen.getByRole('button', { name: 'Стоп' }).focus()

    rerender(<SearchForm {...props} active={false} />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Найти' })).toHaveFocus(),
    )
  })
})
