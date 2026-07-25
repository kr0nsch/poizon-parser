import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

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

describe('SearchStatus', () => {
  it('renders live progress without HTML injection', () => {
    render(
      <SearchStatus
        job={snapshot()}
        actionPending={false}
        onCancel={vi.fn()}
        onPause={vi.fn()}
        onResume={vi.fn()}
      />,
    )

    expect(screen.getByText('Проверяю карточки Nike')).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '25')
    expect(screen.getByText('Из кэша: 2')).toBeInTheDocument()
  })

  it('lets the user resume after a captcha pause', async () => {
    const onResume = vi.fn()
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
        onCancel={vi.fn()}
        onPause={vi.fn()}
        onResume={onResume}
      />,
    )

    await user.click(screen.getByRole('button', { name: 'Продолжить' }))
    expect(onResume).toHaveBeenCalledOnce()
    expect(
      screen.getByRole('link', { name: 'Открыть проверку' }),
    ).toHaveAttribute('target', '_blank')
  })
})
