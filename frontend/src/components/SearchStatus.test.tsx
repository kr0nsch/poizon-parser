import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { SearchSnapshot } from '../api'
import { SearchStatus } from './SearchStatus'

function snapshot(overrides: Partial<SearchSnapshot> = {}): SearchSnapshot {
  return {
    id: 'job-1',
    status: 'running',
    phase: 'check',
    brand: { id: 1, name: 'Nike', url: '/nike' },
    collected: 40,
    checked: 10,
    total: 40,
    found: 2,
    matches: [],
    log: ['карточка 10 из 40'],
    error: '',
    paused: false,
    captcha: null,
    cooldown_until: 0,
    prefiltered: 0,
    stats: { requests: 10, cache_hits: 2 },
    activity: 'читаю карточку',
    active_requests: 1,
    last_activity_at: Date.now() / 1_000,
    pause_requested: false,
    stop_reason: '',
    started_at: Date.now() / 1_000 - 20,
    finished_at: null,
    idle_seconds: 0,
    ...overrides,
  }
}

const handlers = () => ({
  onCancel: vi.fn(),
  onPause: vi.fn(),
  onResume: vi.fn(),
})

describe('SearchStatus', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders live progress without HTML injection', () => {
    render(
      <SearchStatus job={snapshot()} actionPending={false} {...handlers()} />,
    )

    expect(
      screen.getByText('Проверяю карточки Nike', {
        selector: '.status-summary__title',
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Проверяю карточки Nike',
    )
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '25')
    expect(screen.getByText('Из кэша: 2')).toBeInTheDocument()
  })

  it('lets the user resume after a captcha pause', async () => {
    const props = handlers()
    const user = userEvent.setup()
    render(
      <SearchStatus
        job={snapshot({
          status: 'captcha',
          captcha: {
            url: 'https://example.test/challenge',
            reason: 'captcha',
            since: Date.now() / 1_000 - 5,
          },
        })}
        actionPending={false}
        {...props}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Продолжить' }))
    expect(props.onResume).toHaveBeenCalledOnce()
    expect(
      screen.getByRole('link', { name: 'Открыть проверку' }),
    ).toHaveAttribute('target', '_blank')
  })

  it('announces changes through live regions that stay mounted', () => {
    const props = handlers()
    const { rerender } = render(
      <SearchStatus job={snapshot()} actionPending={false} {...props} />,
    )
    const status = screen.getByRole('status')
    const alert = screen.getByRole('alert')
    expect(alert).toBeEmptyDOMElement()

    rerender(
      <SearchStatus
        job={snapshot({
          status: 'captcha',
          paused: true,
          captcha: { url: null, reason: 'captcha', since: Date.now() / 1_000 },
        })}
        actionPending={false}
        {...props}
      />,
    )
    expect(screen.getByRole('alert')).toBe(alert)
    expect(alert).toHaveTextContent(/^Поиск поставлен на паузу\. Пройдите/)
    expect(status).toBeEmptyDOMElement()

    rerender(
      <SearchStatus
        job={snapshot({
          status: 'done',
          checked: 40,
          finished_at: Date.now() / 1_000,
        })}
        actionPending={false}
        {...props}
      />,
    )
    expect(screen.getByRole('status')).toBe(status)
    expect(status).toHaveTextContent(
      'Поиск завершён. Проверено 40 из 40, найдено 2',
    )
    expect(alert).toBeEmptyDOMElement()
  })

  it('shows an indeterminate brand lookup instead of 0 of 0', () => {
    render(
      <SearchStatus
        job={snapshot({
          phase: 'brand',
          brand: null,
          collected: 0,
          checked: 0,
          total: 0,
        })}
        actionPending={false}
        {...handlers()}
      />,
    )

    expect(screen.getByRole('status')).toHaveTextContent('Ищу бренд…')
    expect(screen.queryByText(/0 из 0/)).not.toBeInTheDocument()
    expect(screen.queryByText(/карточки бренда/)).not.toBeInTheDocument()
    expect(screen.getByRole('progressbar')).not.toHaveAttribute('value')
  })

  it('counts idle time from the server value, not the browser clock', () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] })
    // Часы сервера отстают от браузера на час: метки времени в снимке
    // «старые», но сервер сам сообщает, что активность была 2 с назад.
    const serverNow = Date.now() / 1_000 - 3_600
    render(
      <SearchStatus
        job={snapshot({
          last_activity_at: serverNow - 2,
          idle_seconds: 2,
          started_at: serverNow - 20,
          cooldown_until: serverNow + 30,
        })}
        actionPending={false}
        {...handlers()}
      />,
    )

    expect(screen.getByText('· активность 2 с назад')).toBeInTheDocument()
    expect(screen.getByText(/Жду 30 с/)).toBeInTheDocument()
    expect(screen.queryByText(/нет ответа/)).not.toBeInTheDocument()

    act(() => {
      vi.advanceTimersByTime(5_000)
    })
    expect(screen.getByText('· активность 7 с назад')).toBeInTheDocument()
    expect(screen.getByText(/Жду 25 с/)).toBeInTheDocument()
  })

  it('lets the user withdraw a manual pause that has not started yet', async () => {
    const props = handlers()
    const user = userEvent.setup()
    render(
      <SearchStatus
        job={snapshot({ pause_requested: true })}
        actionPending={false}
        {...props}
      />,
    )

    const button = screen.getByRole('button', { name: 'Отменить паузу' })
    expect(button).toBeEnabled()
    expect(button).not.toHaveAttribute('aria-disabled')
    expect(screen.getByRole('status')).toHaveTextContent(
      'Встаю на паузу после текущих запросов',
    )

    await user.click(button)
    expect(props.onResume).toHaveBeenCalledOnce()
    expect(props.onPause).not.toHaveBeenCalled()
  })

  it('moves focus to «Продолжить» when the pause button disappears', async () => {
    const props = handlers()
    const { rerender } = render(
      <SearchStatus job={snapshot()} actionPending={false} {...props} />,
    )
    screen.getByRole('button', { name: 'Пауза / пройти проверку' }).focus()

    rerender(
      <SearchStatus
        job={snapshot({
          status: 'captcha',
          paused: true,
          captcha: { url: null, reason: 'manual', since: Date.now() / 1_000 },
        })}
        actionPending={false}
        {...props}
      />,
    )

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Продолжить' })).toHaveFocus(),
    )
  })

  it('keeps focus in the card after cancelling from the captcha panel', async () => {
    const props = handlers()
    const captcha = snapshot({
      status: 'captcha',
      paused: true,
      captcha: { url: null, reason: 'captcha', since: Date.now() / 1_000 },
    })
    const { container, rerender } = render(
      <SearchStatus job={captcha} actionPending={false} {...props} />,
    )
    screen.getByRole('button', { name: 'Отменить' }).focus()

    rerender(
      <SearchStatus
        job={{ ...captcha, status: 'cancelled', paused: false, captcha: null }}
        actionPending={false}
        {...props}
      />,
    )

    // Панель капчи уходит с анимацией; после удаления фокус — на сводке.
    await waitFor(() =>
      expect(container.querySelector('.status-summary')).toHaveFocus(),
    )
    expect(
      screen.queryByRole('button', { name: 'Отменить' }),
    ).not.toBeInTheDocument()
  })
})
