import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, PackageSearch, SearchX, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'

import {
  ApiError,
  addPick,
  cancelSearch,
  clearPicks,
  convertSize,
  createReport,
  getBrands,
  getPicks,
  isActiveSearchStatus,
  isTerminalSearchStatus,
  matchKey,
  pauseSearch,
  removePick,
  resumeSearch,
  startSearch,
  type PicksResponse,
  type ReportResponse,
  type SearchMatch,
  type SearchRequest,
  type SearchSnapshot,
} from './api'
import { AppShell, type AppView } from './components/AppShell'
import { EmptyState } from './components/EmptyState'
import { MotionView } from './components/MotionView'
import { PicksView } from './components/PicksView'
import {
  DEFAULT_RESULTS_FILTERS,
  ResultsView,
  type ResultsFilters,
} from './components/ResultsView'
import { SearchForm } from './components/SearchForm'
import { SearchStatus } from './components/SearchStatus'
import { Button } from './components/ui'
import { isPermanentPollError, searchJobQueryKey, useSearchJob } from './hooks'
import {
  loadSearchForm,
  saveSearchForm,
  type StoredSearchForm,
} from './lib/storage'
import { useFocusRescue, useListFocusRescue } from './lib/utils'

const PICKS_QUERY_KEY = ['picks'] as const

const LOST_JOB_MESSAGE =
  'Сервер больше не знает об этой задаче — скорее всего, он перезапускался. Найденное осталось на экране; чтобы продолжить, запустите поиск заново.'

type SearchAction = 'cancel' | 'pause' | 'resume'

/** Запущенный поиск: id задачи и параметры, с которыми он запущен. */
interface ActiveSearch {
  jobId: string
  request: SearchRequest
}

interface ReportVariables {
  brand?: string
  embed: boolean
  /** Сервер ещё знает задачу — можно прислать только ключи строк. */
  jobAvailable: boolean
  jobId: string
  matches: SearchMatch[]
  request?: SearchRequest
}

interface Banner {
  id: string
  message: string
  onDismiss: () => void
}

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) {
    return String(error.message)
  }
  return 'Не удалось выполнить запрос. Проверьте, что локальный сервер запущен.'
}

/** Текст ошибки как отдельное предложение: с точкой в конце. */
function asSentence(text: string): string {
  const trimmed = text.trim()
  return /[.!?…]$/.test(trimmed) ? trimmed : `${trimmed}.`
}

function parseFoot(size: string): number {
  return Number(String(size).replace(',', '.'))
}

function buildSearchRequest(form: StoredSearchForm): SearchRequest {
  return {
    brand: form.brand.trim(),
    size: form.size.trim(),
    scale: 'CM',
    gender: form.gender,
    depth: Number(form.depth) || 0,
    maxPrice: form.maxPrice ? Number(form.maxPrice) : null,
    pace: form.pace,
    kids: form.kids,
  }
}

function withKey(keys: ReadonlySet<string>, key: string): ReadonlySet<string> {
  const next = new Set(keys)
  next.add(key)
  return next
}

function withoutKey(
  keys: ReadonlySet<string>,
  key: string,
): ReadonlySet<string> {
  if (!keys.has(key)) return keys
  const next = new Set(keys)
  next.delete(key)
  return next
}

/**
 * Отчёт по видимым строкам. Пока задача жива, шлём только ключи строк —
 * тело остаётся маленьким при любом числе результатов; если сервер задачу
 * уже не знает, присылаем строки целиком.
 */
async function requestReport({
  brand,
  embed,
  jobAvailable,
  jobId,
  matches,
  request,
}: ReportVariables): Promise<ReportResponse> {
  // Параметры — того поиска, что дал результаты, а не текущей формы.
  const meta = {
    jobId,
    brand,
    size: request?.size,
    scale: request?.scale ?? 'CM',
    gender: request?.gender,
    embed,
  }
  if (jobAvailable) {
    try {
      return await createReport({
        ...meta,
        keys: matches.map(({ spu_id, sku_id }) => ({ spu_id, sku_id })),
      })
    } catch (error) {
      const fallback =
        error instanceof ApiError &&
        (error.status === 404 || error.status === 409)
      if (!fallback) throw error
    }
  }
  return createReport({ ...meta, matches })
}

/** Первый из элементов по селекторам, который сейчас есть на странице. */
function firstPresent(...selectors: string[]): HTMLElement | null {
  for (const selector of selectors) {
    const element = document.querySelector<HTMLElement>(selector)
    if (element) return element
  }
  return null
}

function Banners({
  banners,
  focusFallback,
}: {
  banners: Banner[]
  /** Куда перенести фокус, когда скрыто последнее сообщение. */
  focusFallback: () => HTMLElement | null | undefined
}) {
  // Скрытое сообщение уносит с собой кнопку «Скрыть»: фокус переходит на
  // соседнее сообщение, а после последнего — на focusFallback().
  const rescueFocus = useListFocusRescue<HTMLDivElement>(focusFallback)
  if (banners.length === 0) return null
  return (
    <div style={{ display: 'grid', gap: '0.4rem', marginTop: '0.75rem' }}>
      {banners.map((banner) => (
        <div
          key={banner.id}
          ref={rescueFocus}
          className="ui-field__error"
          role="alert"
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
        >
          <span style={{ flex: 1 }}>{banner.message}</span>
          <Button
            size="icon"
            variant="quiet"
            aria-label="Скрыть сообщение"
            title="Скрыть"
            onClick={banner.onDismiss}
          >
            <X size={14} aria-hidden="true" />
          </Button>
        </div>
      ))}
    </div>
  )
}

export function App() {
  const queryClient = useQueryClient()
  const [activeView, setActiveView] = useState<AppView>('search')
  const [form, setForm] = useState<StoredSearchForm>(loadSearchForm)
  const [search, setSearch] = useState<ActiveSearch | null>(null)
  const jobId = search?.jobId ?? null
  const [report, setReport] = useState<{
    jobId: string
    response: ReportResponse
  }>()
  const [resultsFilters, setResultsFilters] = useState<ResultsFilters>(
    DEFAULT_RESULTS_FILTERS,
  )
  const [savingKeys, setSavingKeys] = useState<ReadonlySet<string>>(
    () => new Set(),
  )
  const [removingIds, setRemovingIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  )
  // Когда скрыли ошибку опроса: она не всплывает снова до первого успеха.
  const [pollErrorDismissedAt, setPollErrorDismissedAt] = useState(0)
  const [conversionInput, setConversionInput] = useState(() => ({
    brand: form.brand.trim(),
    foot: parseFoot(form.size),
    gender: form.gender,
  }))
  // Текущая задача — для ответов, пришедших уже после смены поиска.
  const jobIdRef = useRef(jobId)
  // Удачный повтор убирает подсказку о брендах вместе с «Повторить»: фокус
  // уходит на поле бренда, где подсказки теперь и появятся.
  const brandInputRef = useRef<HTMLInputElement>(null)
  const rescueBrandsRetryFocus = useFocusRescue<HTMLButtonElement>(
    () => brandInputRef.current,
  )
  // После последнего скрытого сообщения — на ближайший раздел экрана.
  const searchBannersFallback = () =>
    firstPresent('#results-title', '.status-summary') ?? brandInputRef.current
  const picksBannersFallback = () =>
    firstPresent('#picks-title', '.empty-state[tabindex]')

  useEffect(() => {
    jobIdRef.current = jobId
  }, [jobId])

  useEffect(() => {
    saveSearchForm(form)
  }, [form])

  useEffect(() => {
    const foot = parseFoot(form.size)
    const timer = window.setTimeout(() => {
      setConversionInput({
        brand: form.brand.trim(),
        foot,
        gender: form.gender,
      })
    }, 250)
    return () => window.clearTimeout(timer)
  }, [form.brand, form.gender, form.size])

  const brandsQuery = useQuery({
    queryKey: ['brands'],
    queryFn: ({ signal }) => getBrands({ signal }),
    staleTime: 10 * 60 * 1_000,
  })

  const conversionQuery = useQuery({
    queryKey: ['size-conversion', conversionInput],
    queryFn: ({ signal }) =>
      convertSize(
        {
          foot: conversionInput.foot,
          brand: conversionInput.brand || undefined,
          gender: conversionInput.gender,
        },
        { signal },
      ),
    enabled:
      Number.isFinite(conversionInput.foot) &&
      conversionInput.foot >= 15 &&
      conversionInput.foot <= 40,
    staleTime: 5 * 60 * 1_000,
    retry: 1,
  })

  const picksQuery = useQuery<PicksResponse, ApiError>({
    queryKey: PICKS_QUERY_KEY,
    queryFn: ({ signal }) => getPicks({ signal }),
  })

  const searchJobQuery = useSearchJob(jobId)
  const job = searchJobQuery.data
  const pollError = searchJobQuery.error
  // 4xx — сервер задачу больше не знает (обычно его перезапустили): опрос
  // остановлен, а последний снимок навсегда остался бы «в работе».
  const jobGone = isPermanentPollError(pollError)
  const jobFinished = job != null && isTerminalSearchStatus(job.status)
  const jobLost = jobGone && !jobFinished
  const lostMessage =
    pollError && jobLost
      ? pollError.status === 404
        ? LOST_JOB_MESSAGE
        : errorMessage(pollError)
      : ''
  const displayJob = useMemo<SearchSnapshot | undefined>(
    () =>
      job && lostMessage
        ? {
            ...job,
            status: 'error',
            stop_reason: 'задача потеряна',
            error: lostMessage,
            pause_requested: false,
            active_requests: 0,
          }
        : job,
    [job, lostMessage],
  )
  const awaitingFirstSnapshot = Boolean(jobId && !job && !jobGone)
  const searchActive =
    !jobLost &&
    ((job ? isActiveSearchStatus(job.status) : false) || awaitingFirstSnapshot)
  const picks = picksQuery.data?.items ?? []
  const visibleReport =
    report && report.jobId === jobId ? report.response : undefined

  const startMutation = useMutation({
    mutationFn: async (request: SearchRequest) => {
      const { id } = await startSearch(request)
      return { jobId: id, request }
    },
    onSuccess: (started) => {
      setSearch(started)
      setResultsFilters(DEFAULT_RESULTS_FILTERS)
      setPollErrorDismissedAt(0)
    },
  })

  const searchActionMutation = useMutation({
    mutationFn: ({
      action,
      jobId: targetJobId,
    }: {
      action: SearchAction
      jobId: string
    }) => {
      if (action === 'cancel') return cancelSearch(targetJobId)
      if (action === 'pause') return pauseSearch(targetJobId)
      // «Продолжить» снимает и капчу, и ещё не сработавшую ручную паузу.
      return resumeSearch(targetJobId)
    },
    onSettled: (_data, _error, { jobId: targetJobId }) =>
      queryClient.invalidateQueries({
        queryKey: searchJobQueryKey(targetJobId),
      }),
  })

  function runSearchAction(action: SearchAction) {
    if (jobId) searchActionMutation.mutate({ action, jobId })
  }

  const addPickMutation = useMutation({
    mutationFn: (match: SearchMatch) =>
      addPick({
        match,
        query: {
          brand: match.brand || job?.brand?.name || search?.request.brand || '',
          size: match.requested_size,
          scale: match.requested_scale,
        },
      }),
    onMutate: (match) => {
      setSavingKeys((keys) => withKey(keys, matchKey(match)))
    },
    onSuccess: (response) => {
      // Уже сохранённая позиция (created: false — например, из другой
      // вкладки) тоже должна стать «В итогах».
      const current = queryClient.getQueryData<PicksResponse>(PICKS_QUERY_KEY)
      if (!current) {
        void queryClient.invalidateQueries({ queryKey: PICKS_QUERY_KEY })
        return
      }
      if (current.items.some((pick) => pick.id === response.item.id)) return
      queryClient.setQueryData<PicksResponse>(PICKS_QUERY_KEY, {
        items: [response.item, ...current.items],
      })
    },
    onSettled: (_data, _error, match) => {
      setSavingKeys((keys) => withoutKey(keys, matchKey(match)))
    },
  })

  const removePickMutation = useMutation({
    mutationFn: async (id: string) => {
      try {
        await removePick(id)
      } catch (error) {
        // Позицию уже убрали (например, в другой вкладке) — цель достигнута.
        if (!(error instanceof ApiError && error.status === 404)) throw error
      }
      return id
    },
    onMutate: (id) => {
      setRemovingIds((ids) => withKey(ids, id))
    },
    onSuccess: (id) => {
      queryClient.setQueryData<PicksResponse>(PICKS_QUERY_KEY, (current) => ({
        items: (current?.items ?? []).filter((pick) => pick.id !== id),
      }))
    },
    onSettled: (_data, _error, id) => {
      setRemovingIds((ids) => withoutKey(ids, id))
      // Сверяемся с сервером: итоги могли поменять в другой вкладке.
      void queryClient.invalidateQueries({ queryKey: PICKS_QUERY_KEY })
    },
  })

  const clearPicksMutation = useMutation({
    mutationFn: () => clearPicks(),
    onSuccess: () =>
      queryClient.setQueryData<PicksResponse>(PICKS_QUERY_KEY, { items: [] }),
  })

  const reportMutation = useMutation({
    mutationFn: requestReport,
    onSuccess: (response, { jobId: reportJobId }) => {
      // Медленный отчёт (с фото) мог прийти уже после нового поиска.
      if (reportJobId !== jobIdRef.current) return
      setReport({ jobId: reportJobId, response })
    },
  })

  function changeView(view: AppView) {
    setActiveView(view)
    // Ошибки действий относятся к экрану, где они случились.
    for (const mutation of [
      startMutation,
      searchActionMutation,
      addPickMutation,
      removePickMutation,
      clearPicksMutation,
      reportMutation,
    ]) {
      if (mutation.isError) mutation.reset()
    }
  }

  const searchBanners: Banner[] = []
  if (
    pollError &&
    !jobGone &&
    pollErrorDismissedAt <= searchJobQuery.dataUpdatedAt
  ) {
    searchBanners.push({
      id: 'poll',
      message: `Не удалось обновить статус поиска: ${errorMessage(pollError)}`,
      onDismiss: () => setPollErrorDismissedAt(Date.now()),
    })
  }
  if (
    searchActionMutation.error &&
    searchActionMutation.variables?.jobId === jobId
  ) {
    searchBanners.push({
      id: 'action',
      message: errorMessage(searchActionMutation.error),
      onDismiss: () => searchActionMutation.reset(),
    })
  }
  if (addPickMutation.error) {
    searchBanners.push({
      id: 'pick',
      message: `Не удалось добавить в итоги: ${errorMessage(addPickMutation.error)}`,
      onDismiss: () => addPickMutation.reset(),
    })
  }
  if (reportMutation.error && reportMutation.variables?.jobId === jobId) {
    searchBanners.push({
      id: 'report',
      message: `Не удалось собрать отчёт: ${errorMessage(reportMutation.error)}`,
      onDismiss: () => reportMutation.reset(),
    })
  }

  const picksBanners: Banner[] = []
  if (removePickMutation.error) {
    picksBanners.push({
      id: 'remove',
      message: `Не удалось убрать позицию: ${errorMessage(removePickMutation.error)}`,
      onDismiss: () => removePickMutation.reset(),
    })
  }
  if (clearPicksMutation.error) {
    picksBanners.push({
      id: 'clear',
      message: `Не удалось очистить итоги: ${errorMessage(clearPicksMutation.error)}`,
      onDismiss: () => clearPicksMutation.reset(),
    })
  }

  const title =
    activeView === 'search' ? 'Найдите свой размер' : 'Сохранённые модели'
  const description =
    activeView === 'search'
      ? 'Введите длину стопы — сервис сверит размерную сетку бренда и покажет модели в наличии с ценой именно за ваш размер.'
      : 'Соберите финальную подборку, сравните цены и передайте её в CSV или JSON.'

  return (
    <AppShell
      activeView={activeView}
      title={title}
      description={description}
      picksCount={picks.length}
      onViewChange={changeView}
    >
      <MotionView viewKey={activeView}>
        {activeView === 'search' ? (
          <>
            <SearchForm
              active={searchActive}
              brandInputRef={brandInputRef}
              brands={brandsQuery.data?.brands ?? []}
              brandsLoading={brandsQuery.isPending}
              conversion={conversionQuery.data}
              conversionLoading={conversionQuery.isFetching}
              error={
                startMutation.error
                  ? errorMessage(startMutation.error)
                  : undefined
              }
              form={form}
              onChange={setForm}
              onSubmit={() => startMutation.mutate(buildSearchRequest(form))}
              onCancel={() => runSearchAction('cancel')}
              starting={startMutation.isPending}
            />

            {brandsQuery.isError ? (
              <p
                className="ui-field__hint"
                role="status"
                style={{ marginTop: '0.6rem' }}
              >
                Подсказки брендов не загрузились — бренд можно ввести вручную.{' '}
                {errorMessage(brandsQuery.error)}{' '}
                <button
                  ref={rescueBrandsRetryFocus}
                  className="inline-link"
                  type="button"
                  onClick={() => void brandsQuery.refetch()}
                >
                  Повторить
                </button>
              </p>
            ) : null}
            {conversionQuery.isError ? (
              <p
                className="ui-field__hint"
                role="status"
                style={{ marginTop: '0.6rem' }}
              >
                {/* Сообщение ошибки — отдельной фразой в скобках: оно бывает
                    и с точкой, и без, и не должно рвать основное предложение. */}
                Не удалось сверить таблицу размеров — поиск работает и без
                подсказки. ({asSentence(errorMessage(conversionQuery.error))})
              </p>
            ) : null}

            {displayJob ? (
              <SearchStatus
                job={displayJob}
                actionPending={searchActionMutation.isPending}
                onPause={() => runSearchAction('pause')}
                onResume={() => runSearchAction('resume')}
                onCancel={() => runSearchAction('cancel')}
              />
            ) : lostMessage ? (
              <div
                className="notice"
                role="status"
                style={{ marginTop: '1rem' }}
              >
                <AlertTriangle size={17} aria-hidden="true" />
                <span>
                  <strong>Задача поиска потеряна.</strong> {lostMessage}
                </span>
              </div>
            ) : null}

            <Banners
              banners={searchBanners}
              focusFallback={searchBannersFallback}
            />

            {job?.matches.length ? (
              <ResultsView
                brand={job.brand?.name || search?.request.brand || form.brand}
                filters={resultsFilters}
                matches={job.matches}
                picks={picks}
                report={visibleReport}
                reporting={
                  reportMutation.isPending &&
                  reportMutation.variables?.jobId === jobId
                }
                savingKeys={savingKeys}
                onFiltersChange={setResultsFilters}
                // mutate стабилен между рендерами: карточки (memo) не
                // перерисовываются на каждом опросе поиска.
                onPick={addPickMutation.mutate}
                onCreateReport={(matches, embed) => {
                  if (!jobId) return
                  reportMutation.mutate({
                    brand: job.brand?.name || search?.request.brand,
                    embed,
                    jobAvailable: !jobGone,
                    jobId,
                    matches,
                    request: search?.request,
                  })
                }}
              />
            ) : job?.status === 'done' ? (
              <div style={{ marginTop: '1rem' }}>
                <EmptyState
                  icon={SearchX}
                  title="Подходящий размер не нашёлся"
                  description="Попробуйте увеличить глубину поиска, снять ограничение цены или проверить другой размер."
                />
              </div>
            ) : !job ? (
              <div style={{ marginTop: '1rem' }}>
                <EmptyState
                  icon={PackageSearch}
                  title="Результаты появятся здесь"
                  description="Выберите бренд и укажите длину стопы. Карточки будут добавляться в этот экран по мере проверки каталога."
                />
              </div>
            ) : null}
          </>
        ) : (
          <>
            <Banners
              banners={picksBanners}
              focusFallback={picksBannersFallback}
            />
            <PicksView
              picks={picks}
              loading={picksQuery.isPending}
              error={
                picksQuery.isError ? errorMessage(picksQuery.error) : undefined
              }
              retrying={picksQuery.isFetching}
              clearing={clearPicksMutation.isPending}
              removingIds={removingIds}
              onRetry={() => void picksQuery.refetch()}
              onRemove={removePickMutation.mutate}
              onClear={() => clearPicksMutation.mutate()}
            />
          </>
        )}
      </MotionView>
    </AppShell>
  )
}
