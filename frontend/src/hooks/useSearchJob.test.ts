import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type SearchSnapshot } from '../api'
import {
  fetchSearchSnapshot,
  isPermanentPollError,
  shouldRetryPoll,
} from './useSearchJob'

function snapshot(overrides: Partial<SearchSnapshot> = {}): SearchSnapshot {
  return {
    id: 'job-1',
    status: 'done',
    phase: 'check',
    brand: { id: 1, name: 'Nike', url: '/nike' },
    collected: 2,
    checked: 2,
    total: 2,
    found: 1,
    matches: [],
    log: [],
    error: '',
    paused: false,
    captcha: null,
    cooldown_until: 0,
    prefiltered: 0,
    stats: {},
    activity: '',
    active_requests: 0,
    last_activity_at: 0,
    pause_requested: false,
    stop_reason: '',
    started_at: 0,
    finished_at: 10,
    idle_seconds: 0,
    ...overrides,
  }
}

function serve(...snapshots: SearchSnapshot[]) {
  const fetchMock = vi.fn(
    async () => new Response(JSON.stringify(snapshots.shift())),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('fetchSearchSnapshot', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('returns a complete final snapshot as is', async () => {
    const fetchMock = serve(snapshot())

    const result = await fetchSearchSnapshot(
      'job-1',
      new AbortController().signal,
    )

    expect(result.finished_at).toBe(10)
    expect(fetchMock).toHaveBeenCalledOnce()
  })

  it('re-reads a final snapshot published before its other fields', async () => {
    const fetchMock = serve(
      snapshot({ finished_at: null, stop_reason: '' }),
      snapshot({ finished_at: 12, stop_reason: 'готово' }),
    )

    const result = await fetchSearchSnapshot(
      'job-1',
      new AbortController().signal,
    )

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(result.finished_at).toBe(12)
    expect(result.stop_reason).toBe('готово')
  })

  it('does not re-read running snapshots', async () => {
    const fetchMock = serve(snapshot({ status: 'running', finished_at: null }))

    await fetchSearchSnapshot('job-1', new AbortController().signal)

    expect(fetchMock).toHaveBeenCalledOnce()
  })
})

describe('isPermanentPollError', () => {
  it('treats only 4xx as permanent', () => {
    const error = (status: number) =>
      new ApiError('x', { status, statusText: '', url: '/api/search/x' })

    expect(isPermanentPollError(error(404))).toBe(true)
    expect(isPermanentPollError(error(502))).toBe(false)
    expect(isPermanentPollError(error(0))).toBe(false)
    expect(isPermanentPollError(null)).toBe(false)
  })
})

describe('shouldRetryPoll', () => {
  const error = (status: number) =>
    new ApiError('x', { status, statusText: '', url: '/api/search/x' })

  afterEach(() => vi.restoreAllMocks())

  it('retries transient errors twice in a visible tab', () => {
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')

    expect(shouldRetryPoll(0, error(0))).toBe(true)
    expect(shouldRetryPoll(1, error(502))).toBe(true)
    expect(shouldRetryPoll(2, error(502))).toBe(false)
    expect(shouldRetryPoll(0, error(404))).toBe(false)
  })

  it('never retries in a hidden tab, so the next interval tick polls again', () => {
    // Повтор в скрытой вкладке встаёт на паузу и останавливает опрос —
    // сервер тогда считает задачу брошенной, хотя страница открыта.
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')

    expect(shouldRetryPoll(0, error(0))).toBe(false)
    expect(shouldRetryPoll(0, error(502))).toBe(false)
  })
})
