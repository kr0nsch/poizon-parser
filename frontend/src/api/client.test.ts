import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, requestJson, statusMessage } from './client'

function mockFetch(body: string, init: ResponseInit) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(body, init)),
  )
}

async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise
  } catch (error) {
    if (error instanceof ApiError) return error
    throw error
  }
  throw new Error('запрос неожиданно прошёл')
}

describe('requestJson', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses the server error text when present', async () => {
    mockFetch(JSON.stringify({ ok: false, error: 'поиск не на паузе' }), {
      status: 409,
      statusText: 'Conflict',
    })

    const error = await failure(requestJson('/api/search/x/continue'))

    expect(error.status).toBe(409)
    expect(error.message).toBe('поиск не на паузе')
  })

  it('explains bare {"ok": false} replies instead of raw status text', async () => {
    mockFetch(JSON.stringify({ ok: false }), {
      status: 409,
      statusText: 'Conflict',
    })

    const error = await failure(requestJson('/api/search/x/pause'))

    expect(error.message).toBe(statusMessage(409))
    expect(error.message).not.toContain('Conflict')
  })

  it('maps non-JSON proxy errors by status', async () => {
    mockFetch('Bad gateway', { status: 502, statusText: 'Bad Gateway' })

    const error = await failure(requestJson('/api/brands'))

    expect(error.status).toBe(502)
    expect(error.message).toContain('Сервер недоступен')
  })

  it('still reports invalid JSON in successful replies', async () => {
    mockFetch('<html>', { status: 200 })

    const error = await failure(requestJson('/api/brands'))

    expect(error.message).toBe('Сервер вернул некорректный JSON')
  })

  it('reports network failures in Russian', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch')
      }),
    )

    const error = await failure(requestJson('/api/picks'))

    expect(error.status).toBe(0)
    expect(error.message).toBe('Не удалось связаться с сервером')
  })
})

describe('statusMessage', () => {
  it('describes common statuses in Russian', () => {
    expect(statusMessage(404)).toContain('Не найдено')
    expect(statusMessage(409)).toContain('недоступно')
    expect(statusMessage(500)).toContain('Внутренняя ошибка')
    expect(statusMessage(418, "I'm a teapot")).toBe(
      "Ошибка API: 418 I'm a teapot",
    )
  })
})
