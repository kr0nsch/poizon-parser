import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Pick } from '../api'
import { PicksView } from './PicksView'

const PICK: Pick = {
  id: 'pick-1',
  saved_at: '2026-10-14 12:00',
  query: { brand: 'Nike', size: 26.5, scale: 'CM' },
  match: {
    spu_id: 1,
    sku_id: 10,
    title: 'Nike Air Max',
    article: 'A1',
    brand: 'Nike',
    url: 'https://www.thepoizon.ru/product/1',
    requested_size: 26.5,
    requested_scale: 'CM',
    converted_eu: 42,
    converted_cm: 26.5,
    converted_foot: 26.5,
    exact_conversion: true,
    conversion_source: 'brand',
    conversion_note: '',
    matched_scale: 'EU',
    size: '42',
    sizes: { EU: '42' },
    price: 9000,
    price_text: '9 000 ₽',
    currency: 'RUB',
    in_stock: true,
    delivery: '5-7 дней',
    variant: '',
    inventory_no: '',
    labels: [],
    product_min_price: 9000,
    size_tip: '',
    image: '',
  },
}

function renderView(props: Partial<Parameters<typeof PicksView>[0]> = {}) {
  const handlers = { onRetry: vi.fn(), onRemove: vi.fn(), onClear: vi.fn() }
  render(
    <PicksView
      picks={[]}
      loading={false}
      clearing={false}
      removingIds={new Set()}
      {...handlers}
      {...props}
    />,
  )
  return handlers
}

describe('PicksView', () => {
  it('shows a load error with retry instead of an empty list', async () => {
    const user = userEvent.setup()
    const { onRetry } = renderView({ error: 'Сервер недоступен.' })

    expect(screen.getByText('Не удалось загрузить итоги')).toBeInTheDocument()
    expect(screen.getByText('Сервер недоступен.')).toBeInTheDocument()
    expect(screen.queryByText('В итогах пока пусто')).toBeNull()

    await user.click(screen.getByRole('button', { name: /Повторить/ }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('keeps cached picks visible when a refresh fails', () => {
    renderView({ picks: [PICK], error: 'Сервер недоступен.' })

    expect(screen.getByText('Nike Air Max')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Не удалось обновить итоги',
    )
  })

  it('tracks several removals at once', () => {
    renderView({
      picks: [PICK, { ...PICK, id: 'pick-2' }],
      removingIds: new Set(['pick-1', 'pick-2']),
    })

    expect(screen.getAllByText('Убираю…')).toHaveLength(2)
  })
})
