import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'
import type { Pick, SearchMatch, SearchSnapshot } from './api'
import { FORM_STORAGE_KEY } from './lib/storage'

interface Call {
  method: string
  path: string
  body: Record<string, unknown> | undefined
}

type Handler = (call: Call) => Response | Promise<Response>

// Имя кнопки может включать модель («В итоги: Nike Air Max»).
const SAVE_BUTTON = /^В итоги(:|$)/
const SAVED_BUTTON = /^В итогах/

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function match(overrides: Partial<SearchMatch> = {}): SearchMatch {
  return {
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
    ...overrides,
  }
}

function snapshot(overrides: Partial<SearchSnapshot> = {}): SearchSnapshot {
  return {
    id: 'job-1',
    status: 'done',
    phase: 'check',
    brand: { id: 1, name: 'Nike', url: '/nike' },
    collected: 2,
    checked: 2,
    total: 2,
    found: 2,
    matches: [
      match(),
      match({ spu_id: 2, sku_id: 20, title: 'Nike Pegasus', price: 7000 }),
    ],
    log: [],
    error: '',
    paused: false,
    captcha: null,
    cooldown_until: 0,
    prefiltered: 0,
    stats: {},
    activity: '',
    active_requests: 0,
    last_activity_at: Date.now() / 1_000,
    pause_requested: false,
    stop_reason: 'готово',
    started_at: Date.now() / 1_000 - 5,
    finished_at: Date.now() / 1_000,
    idle_seconds: 0,
    ...overrides,
  }
}

function pick(overrides: Partial<Pick> = {}): Pick {
  return {
    id: 'pick-1',
    saved_at: '2026-10-14 12:00',
    query: { brand: 'Nike', size: 26.5, scale: 'CM' },
    match: match(),
    ...overrides,
  }
}

/** Мини-сервер на подменённом fetch: маршруты «МЕТОД /путь». */
function installServer(routes: Record<string, Handler>) {
  const calls: Call[] = []
  const allRoutes: Record<string, Handler> = {
    'GET /api/brands': () => json({ brands: [] }),
    'GET /api/picks': () => json({ items: [] }),
    'GET /api/convert': () => json({ sizes: null, compare: [] }),
    ...routes,
  }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).split('?')[0] ?? ''
      const method = init?.method ?? 'GET'
      const body =
        typeof init?.body === 'string'
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : undefined
      const call = { method, path, body }
      calls.push(call)
      const handler = allRoutes[`${method} ${path}`]
      return handler ? handler(call) : json({ error: 'не найдено' }, 404)
    }),
  )
  return {
    calls,
    callsTo: (method: string, path: string) =>
      calls.filter((call) => call.method === method && call.path === path),
  }
}

function renderApp() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  })
  const user = userEvent.setup()
  render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
  return { user }
}

function searchButton() {
  return screen.getByRole('button', { name: /^(Найти|Ищу…)$/ })
}

async function startSearch(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: /^Найти$/ }))
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('App', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem(
      FORM_STORAGE_KEY,
      JSON.stringify({ brand: 'Nike', size: '26.5', gender: 'men' }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders even when saved form data has wrong types', () => {
    localStorage.setItem(
      FORM_STORAGE_KEY,
      JSON.stringify({ brand: null, size: 26, gender: 1 }),
    )
    installServer({})

    renderApp()

    expect(searchButton()).toBeEnabled()
  })

  it('surfaces a failed brand list without blocking the form', async () => {
    let fail = true
    installServer({
      'GET /api/brands': () =>
        fail
          ? new Response('Bad gateway', { status: 502 })
          : json({ brands: [] }),
    })
    const { user } = renderApp()

    expect(
      await screen.findByText(/Подсказки брендов не загрузились/),
    ).toHaveTextContent('Сервер недоступен')
    expect(searchButton()).toBeEnabled()

    fail = false
    await user.click(screen.getByRole('button', { name: 'Повторить' }))
    await waitFor(() =>
      expect(screen.queryByText(/Подсказки брендов не загрузились/)).toBeNull(),
    )
  })

  it('unblocks the search when the server forgets the job', async () => {
    let polls = 0
    installServer({
      'POST /api/search': () => json({ id: 'job-1' }),
      'GET /api/search/job-1': () =>
        ++polls === 1
          ? json(snapshot({ status: 'running', finished_at: null }))
          : json({ error: 'задача не найдена' }, 404),
    })
    const { user } = renderApp()

    await startSearch(user)
    await waitFor(() => expect(searchButton()).toHaveTextContent('Ищу…'))

    await waitFor(
      () => expect(screen.getByText('Ошибка: задача потеряна')).toBeVisible(),
      { timeout: 3_000 },
    )
    expect(searchButton()).toHaveTextContent('Найти')
    expect(searchButton()).toBeEnabled()
    expect(screen.queryByRole('button', { name: /^Стоп$/ })).toBeNull()
    // Найденное до потери задачи остаётся на экране.
    expect(screen.getByText('Nike Air Max')).toBeInTheDocument()
  })

  it('withdraws a pending manual pause through the resume endpoint', async () => {
    let pauseRequested = true
    const server = installServer({
      'POST /api/search': () => json({ id: 'job-1' }),
      'GET /api/search/job-1': () =>
        json(
          snapshot({
            status: 'running',
            finished_at: null,
            pause_requested: pauseRequested,
          }),
        ),
      'POST /api/search/job-1/continue': () => {
        pauseRequested = false
        return json({ ok: true })
      },
    })
    const { user } = renderApp()

    await startSearch(user)
    await user.click(
      await screen.findByRole('button', { name: /Отменить паузу/ }),
    )

    expect(server.callsTo('POST', '/api/search/job-1/continue')).toHaveLength(1)
    expect(
      await screen.findByRole('button', { name: /Пауза/ }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Скрыть сообщение' }),
    ).toBeNull()
  })

  it('builds the report from the search that ran, by row keys', async () => {
    const server = installServer({
      'POST /api/search': () => json({ id: 'job-1' }),
      'GET /api/search/job-1': () => json(snapshot()),
      'POST /api/report': () =>
        json({
          dir: 'result/nike',
          file: 'result/nike/index.html',
          view: '/result/nike/index.html',
        }),
    })
    const { user } = renderApp()

    await startSearch(user)
    await screen.findByText('Nike Pegasus')
    // Форму поправили после поиска — отчёт всё равно о 26,5 см.
    const size = screen.getByLabelText(/Длина стопы/)
    await user.clear(size)
    await user.type(size, '27')
    await user.click(screen.getByRole('button', { name: /HTML-отчёт/ }))

    await screen.findByText('Отчёт готов')
    const [call] = server.callsTo('POST', '/api/report')
    expect(call?.body).toMatchObject({
      jobId: 'job-1',
      size: '26.5',
      gender: 'men',
      // Сначала дешевле — порядок как на экране.
      keys: [
        { spu_id: 2, sku_id: 20 },
        { spu_id: 1, sku_id: 10 },
      ],
    })
    expect(call?.body).not.toHaveProperty('matches')
  })

  it('falls back to full rows when the job is gone', async () => {
    const server = installServer({
      'POST /api/search': () => json({ id: 'job-1' }),
      'GET /api/search/job-1': () => json(snapshot()),
      'POST /api/report': ({ body }) =>
        body?.keys
          ? json({ error: 'задача не найдена' }, 404)
          : json({
              dir: 'd',
              file: 'd/index.html',
              view: '/result/d/index.html',
            }),
    })
    const { user } = renderApp()

    await startSearch(user)
    await screen.findByText('Nike Pegasus')
    await user.click(screen.getByRole('button', { name: /HTML-отчёт/ }))

    await screen.findByText('Отчёт готов')
    const calls = server.callsTo('POST', '/api/report')
    expect(calls).toHaveLength(2)
    expect(calls[1]?.body?.matches).toHaveLength(2)
  })

  it('ignores a late report from an earlier search', async () => {
    const slowReport = deferred<Response>()
    let searches = 0
    installServer({
      'POST /api/search': () => json({ id: `job-${++searches}` }),
      'GET /api/search/job-1': () => json(snapshot({ id: 'job-1' })),
      'GET /api/search/job-2': () =>
        json(
          snapshot({
            id: 'job-2',
            matches: [match({ spu_id: 3, sku_id: 30, title: 'Nike Dunk' })],
          }),
        ),
      'POST /api/report': ({ body }) =>
        body?.jobId === 'job-1'
          ? slowReport.promise
          : json({
              dir: 'b',
              file: 'b/index.html',
              view: '/result/b/index.html',
            }),
    })
    const { user } = renderApp()

    await startSearch(user)
    await screen.findByText('Nike Pegasus')
    await user.click(screen.getByRole('button', { name: /HTML-отчёт/ }))

    await startSearch(user)
    await screen.findByText('Nike Dunk')
    slowReport.resolve(
      json({ dir: 'a', file: 'a/index.html', view: '/result/a/index.html' }),
    )
    await new Promise((done) => setTimeout(done, 50))
    expect(screen.queryByText('Отчёт готов')).toBeNull()

    await user.click(screen.getByRole('button', { name: /HTML-отчёт/ }))
    await screen.findByText('Отчёт готов')
    expect(screen.getByRole('link', { name: /Открыть$/ })).toHaveAttribute(
      'href',
      '/result/b/index.html',
    )
  })

  it('marks an already saved position as picked', async () => {
    installServer({
      'POST /api/search': () => json({ id: 'job-1' }),
      'GET /api/search/job-1': () =>
        json(snapshot({ matches: [match()], found: 1 })),
      'POST /api/picks': () =>
        json({ item: pick({ id: 'from-other-tab' }), created: false }),
    })
    const { user } = renderApp()

    await startSearch(user)
    await user.click(await screen.findByRole('button', { name: SAVE_BUTTON }))

    expect(
      await screen.findByRole('button', { name: SAVED_BUTTON }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: SAVE_BUTTON })).toBeNull()
  })

  it('treats a pick deleted elsewhere as removed', async () => {
    let items = [pick()]
    installServer({
      'GET /api/picks': () => json({ items }),
      'DELETE /api/picks/pick-1': () => {
        items = []
        return json({ ok: false, error: 'позиции уже нет в итогах' }, 404)
      },
    })
    const { user } = renderApp()

    await user.click(screen.getAllByRole('button', { name: /Итоги/ })[0]!)
    await user.click(
      await screen.findByRole('button', { name: /Убрать Nike Air Max/ }),
    )

    await screen.findByText('В итогах пока пусто')
    expect(screen.queryByText(/Не удалось убрать позицию/)).toBeNull()
  })

  it('shows a failed picks load with a retry instead of an empty list', async () => {
    let fail = true
    installServer({
      'GET /api/picks': () =>
        fail
          ? json({ error: 'внутренняя ошибка сервера' }, 500)
          : json({ items: [pick()] }),
    })
    const { user } = renderApp()

    await user.click(screen.getAllByRole('button', { name: /Итоги/ })[0]!)
    expect(await screen.findByText('Не удалось загрузить итоги')).toBeVisible()
    expect(screen.queryByText('В итогах пока пусто')).toBeNull()

    fail = false
    await user.click(screen.getByRole('button', { name: /Повторить/ }))
    expect(await screen.findByText('Nike Air Max')).toBeInTheDocument()
  })

  it('lets the user dismiss an error banner and clears it on tab change', async () => {
    installServer({
      'POST /api/search': () => json({ id: 'job-1' }),
      'GET /api/search/job-1': () =>
        json(snapshot({ matches: [match()], found: 1 })),
      'POST /api/picks': () => json({ error: 'диск переполнен' }, 500),
    })
    const { user } = renderApp()

    await startSearch(user)
    const save = await screen.findByRole('button', { name: SAVE_BUTTON })
    await user.click(save)
    const banner = await screen.findByText(/Не удалось добавить в итоги/)
    expect(banner).toHaveTextContent('диск переполнен')
    await user.click(screen.getByRole('button', { name: 'Скрыть сообщение' }))
    expect(screen.queryByText(/Не удалось добавить в итоги/)).toBeNull()

    await user.click(save)
    await screen.findByText(/Не удалось добавить в итоги/)
    await user.click(screen.getAllByRole('button', { name: /Итоги/ })[0]!)
    // Уходящий экран ещё доигрывает анимацию — ждём, пока он исчезнет.
    await waitFor(() =>
      expect(screen.queryByText(/Не удалось добавить в итоги/)).toBeNull(),
    )
    await user.click(screen.getAllByRole('button', { name: /Поиск/ })[0]!)
    await screen.findByRole('button', { name: SAVE_BUTTON })
    expect(screen.queryByText(/Не удалось добавить в итоги/)).toBeNull()
  })

  it('keeps result filters across tab switches', async () => {
    installServer({
      'POST /api/search': () => json({ id: 'job-1' }),
      'GET /api/search/job-1': () => json(snapshot()),
    })
    const { user } = renderApp()

    await startSearch(user)
    await screen.findByText('Nike Pegasus')
    await user.type(screen.getByLabelText('Фильтр по названию'), 'Pegasus')
    await user.selectOptions(
      screen.getByLabelText('Сортировка результатов'),
      'priceDesc',
    )

    await user.click(screen.getAllByRole('button', { name: /Итоги/ })[0]!)
    await user.click(screen.getAllByRole('button', { name: /Поиск/ })[0]!)

    expect(await screen.findByLabelText('Фильтр по названию')).toHaveValue(
      'Pegasus',
    )
    expect(screen.getByLabelText('Сортировка результатов')).toHaveValue(
      'priceDesc',
    )
    const filters = screen.getByLabelText('Активные фильтры')
    expect(within(filters).getByText(/Pegasus/)).toBeInTheDocument()
  })
})
