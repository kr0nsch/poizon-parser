import { render, screen, waitFor } from '@testing-library/react'
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

  it('keeps keyboard focus in the list when a pick is removed', async () => {
    const dunk: Pick = {
      ...PICK,
      id: 'pick-2',
      match: { ...PICK.match, spu_id: 2, sku_id: 20, title: 'Nike Dunk' },
    }
    const props = {
      loading: false,
      clearing: false,
      onRetry: vi.fn(),
      onRemove: vi.fn(),
      onClear: vi.fn(),
    }
    const { container, rerender } = render(
      <PicksView {...props} picks={[PICK, dunk]} removingIds={new Set()} />,
    )
    const remove = screen.getByRole('button', {
      name: 'Убрать Nike Air Max из итогов',
    })
    remove.focus()
    rerender(
      <PicksView
        {...props}
        picks={[PICK, dunk]}
        removingIds={new Set(['pick-1'])}
      />,
    )
    expect(remove).toHaveFocus()

    rerender(<PicksView {...props} picks={[dunk]} removingIds={new Set()} />)

    // Карточка уходит с анимацией; после удаления фокус — на «Убрать»
    // следующей карточки, а не на <body>.
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Убрать Nike Dunk из итогов' }),
      ).toHaveFocus(),
    )
    expect(screen.queryByText('Nike Air Max')).toBeNull()

    rerender(<PicksView {...props} picks={[]} removingIds={new Set()} />)

    // Последняя позиция убрана — фокус на пустом состоянии.
    await waitFor(() =>
      expect(container.querySelector('.empty-state')).toHaveFocus(),
    )
  })

  it('moves focus to the empty state after «Очистить всё»', async () => {
    const props = {
      loading: false,
      onRetry: vi.fn(),
      onRemove: vi.fn(),
      onClear: vi.fn(),
      removingIds: new Set<string>(),
    }
    const { container, rerender } = render(
      <PicksView {...props} picks={[PICK]} clearing={false} />,
    )
    screen.getByRole('button', { name: /Очистить всё/ }).focus()
    rerender(<PicksView {...props} picks={[PICK]} clearing />)
    rerender(<PicksView {...props} picks={[]} clearing={false} />)

    await waitFor(() =>
      expect(container.querySelector('.empty-state')).toHaveFocus(),
    )
  })

  it('keeps focus on the picks after a successful retry', async () => {
    const props = {
      loading: false,
      clearing: false,
      removingIds: new Set<string>(),
      onRetry: vi.fn(),
      onRemove: vi.fn(),
      onClear: vi.fn(),
    }
    const { container, rerender } = render(
      <PicksView {...props} picks={[]} error="Сервер недоступен." />,
    )
    screen.getByRole('button', { name: /Повторить/ }).focus()

    // Итоги загрузились: экран ошибки исчез вместе с «Повторить».
    rerender(<PicksView {...props} picks={[PICK]} />)
    await waitFor(() =>
      expect(container.querySelector('#picks-title')).toHaveFocus(),
    )

    // То же для «Повторить» в сообщении над сохранёнными итогами.
    rerender(<PicksView {...props} picks={[PICK]} error="Сервер недоступен." />)
    screen.getByRole('button', { name: /Повторить/ }).focus()
    rerender(<PicksView {...props} picks={[PICK]} />)
    expect(screen.queryByRole('button', { name: /Повторить/ })).toBeNull()
    await waitFor(() =>
      expect(container.querySelector('#picks-title')).toHaveFocus(),
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
