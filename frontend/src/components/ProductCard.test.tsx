import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { SearchMatch } from '../api'
import { fitHint } from '../lib/format'
import { ProductCard } from './ProductCard'

// Считаем рендеры карточки по вызовам fitHint: он выполняется на каждый рендер.
vi.mock('../lib/format', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/format')>()
  return { ...actual, fitHint: vi.fn(actual.fitHint) }
})

const match: SearchMatch = {
  spu_id: 101,
  sku_id: 202,
  title: 'Nike Air Max',
  article: 'AM-101',
  brand: 'Nike',
  url: 'https://example.com/product',
  requested_size: 26.5,
  requested_scale: 'CM',
  converted_eu: 42,
  converted_cm: 26.5,
  converted_foot: 25.8,
  exact_conversion: false,
  conversion_source: 'brand',
  conversion_note: 'По таблице бренда',
  matched_scale: 'EU',
  size: '42',
  sizes: { EU: '42' },
  price: 12_990,
  price_text: '12 990 ₽',
  currency: 'RUB',
  in_stock: true,
  delivery: 'Доставка 5–7 дней',
  variant: 'Белый / зелёный',
  inventory_no: 'INV-202',
  labels: [],
  product_min_price: 12_990,
  size_tip: 'Идёт в размер',
  image: '',
}

describe('ProductCard', () => {
  it('reveals product details and keeps the pick action working', async () => {
    const user = userEvent.setup()
    const onPick = vi.fn()

    render(<ProductCard match={match} onPick={onPick} />)

    expect(screen.queryByText('Артикул AM-101')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /детали/i }))

    expect(screen.getByRole('region', { name: /детали/i })).toBeInTheDocument()
    expect(screen.getByText('Артикул AM-101')).toBeInTheDocument()
    expect(screen.getByText('Вариант Белый / зелёный')).toBeInTheDocument()
    expect(
      screen.getByText('Приблизительный перевод · По таблице бренда'),
    ).toBeInTheDocument()
    expect(screen.getByText('Стопа 25,8 см')).toBeInTheDocument()
    expect(screen.getByText('CM/JP 26,5 см')).toBeInTheDocument()
    expect(screen.getByText('Инвентарный № INV-202')).toBeInTheDocument()

    await user.click(
      screen.getByRole('button', { name: 'В итоги: Nike Air Max' }),
    )
    expect(onPick).toHaveBeenCalledOnce()
    expect(onPick).toHaveBeenCalledWith(match)
  })

  it('does not call an official foot length a label', () => {
    render(
      <ProductCard
        match={{
          ...match,
          brand: 'New Balance',
          converted_cm: 26.5,
          converted_foot: 26.5,
          exact_conversion: true,
        }}
      />,
    )

    expect(screen.getByText('Стопа 26,5 см')).toBeInTheDocument()
    expect(screen.queryByText(/ярлык/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/CM\/JP/)).not.toBeInTheDocument()
  })

  it('gives every card action a name that includes the model', () => {
    render(
      <>
        <ProductCard match={match} />
        <ProductCard
          match={{ ...match, spu_id: 102, title: 'Nike Dunk Low' }}
          picked
        />
      </>,
    )

    expect(
      screen
        .getAllByRole('link', { name: /^Открыть/ })
        .map((link) => link.getAttribute('aria-label')),
    ).toEqual([
      'Открыть Nike Air Max на POIZON',
      'Открыть Nike Dunk Low на POIZON',
    ])
    expect(
      screen.getByRole('button', { name: 'Детали: Nike Dunk Low' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'В итоги: Nike Air Max' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'В итогах: Nike Dunk Low' }),
    ).toBeInTheDocument()
  })

  it('keeps focus on the pick button after the model is saved', async () => {
    const user = userEvent.setup()
    const onPick = vi.fn()
    const { rerender } = render(<ProductCard match={match} onPick={onPick} />)

    const button = screen.getByRole('button', { name: 'В итоги: Nike Air Max' })
    button.focus()
    rerender(<ProductCard match={match} onPick={onPick} saving />)
    rerender(<ProductCard match={match} onPick={onPick} picked />)

    const saved = screen.getByRole('button', { name: 'В итогах: Nike Air Max' })
    expect(saved).toBe(button)
    expect(saved).toHaveFocus()
    expect(saved).toHaveAttribute('aria-disabled', 'true')

    await user.click(saved)
    expect(onPick).not.toHaveBeenCalled()
  })

  it('skips re-rendering when the props did not change', () => {
    const onPick = vi.fn()
    const renders = vi.mocked(fitHint)
    const { rerender } = render(<ProductCard match={match} onPick={onPick} />)
    const initial = renders.mock.calls.length

    rerender(<ProductCard match={match} onPick={onPick} />)
    expect(renders.mock.calls.length).toBe(initial)

    rerender(<ProductCard match={match} onPick={onPick} saving />)
    expect(renders.mock.calls.length).toBe(initial + 1)
  })
})
