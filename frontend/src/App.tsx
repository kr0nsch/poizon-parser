import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PackageSearch, SearchX } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import {
  addPick,
  cancelSearch,
  clearPicks,
  convertSize,
  createReport,
  getBrands,
  getPicks,
  isActiveSearchStatus,
  pauseSearch,
  removePick,
  resumeSearch,
  startSearch,
  type ApiError,
  type PicksResponse,
  type ReportResponse,
  type SearchMatch,
} from './api'
import { AppShell, type AppView } from './components/AppShell'
import { EmptyState } from './components/EmptyState'
import { PicksView } from './components/PicksView'
import { ResultsView } from './components/ResultsView'
import { SearchForm } from './components/SearchForm'
import { SearchStatus } from './components/SearchStatus'
import { useSearchJob } from './hooks'
import {
  loadSearchForm,
  saveSearchForm,
  type StoredSearchForm,
} from './lib/storage'
import './styles/app.css'

const PICKS_QUERY_KEY = ['picks'] as const

function errorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) {
    return String(error.message)
  }
  return 'Не удалось выполнить запрос. Проверьте, что локальный сервер запущен.'
}

export function App() {
  const queryClient = useQueryClient()
  const [activeView, setActiveView] = useState<AppView>('search')
  const [form, setForm] = useState<StoredSearchForm>(loadSearchForm)
  const [jobId, setJobId] = useState<string | null>(null)
  const [report, setReport] = useState<ReportResponse>()
  const [conversionInput, setConversionInput] = useState(() => ({
    brand: form.brand,
    foot: Number(form.size),
    gender: form.gender,
  }))
  const [savingSpuId, setSavingSpuId] = useState<number>()
  const [removingPickId, setRemovingPickId] = useState<string>()

  useEffect(() => {
    saveSearchForm(form)
  }, [form])

  useEffect(() => {
    const foot = Number(String(form.size).replace(',', '.'))
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
  const permanentPollError =
    searchJobQuery.error != null &&
    searchJobQuery.error.status >= 400 &&
    searchJobQuery.error.status < 500
  const awaitingFirstSnapshot = Boolean(jobId && !job && !permanentPollError)
  const searchActive =
    (job ? isActiveSearchStatus(job.status) : false) || awaitingFirstSnapshot
  const picks = picksQuery.data?.items ?? []

  const startMutation = useMutation({
    mutationFn: () =>
      startSearch({
        brand: form.brand.trim(),
        size: form.size.trim(),
        scale: 'CM',
        gender: form.gender,
        depth: Number(form.depth) || 0,
        maxPrice: form.maxPrice ? Number(form.maxPrice) : null,
        pace: form.pace,
        kids: form.kids,
      }),
    onMutate: () => setReport(undefined),
    onSuccess: ({ id }) => setJobId(id),
  })

  const searchActionMutation = useMutation({
    mutationFn: async (action: 'cancel' | 'pause' | 'resume') => {
      if (!jobId) return
      if (action === 'cancel') await cancelSearch(jobId)
      if (action === 'pause') await pauseSearch(jobId)
      if (action === 'resume') await resumeSearch(jobId)
    },
    onSuccess: async () => {
      await searchJobQuery.refetch()
    },
  })

  const addPickMutation = useMutation({
    mutationFn: async (match: SearchMatch) => {
      setSavingSpuId(match.spu_id)
      return addPick({
        match,
        query: {
          brand: match.brand || job?.brand?.name || form.brand,
          size: match.requested_size,
          scale: match.requested_scale,
        },
      })
    },
    onSuccess: (response) => {
      queryClient.setQueryData<PicksResponse>(PICKS_QUERY_KEY, (current) => {
        if (!response.created) return current
        return { items: [response.item, ...(current?.items ?? [])] }
      })
    },
    onSettled: () => setSavingSpuId(undefined),
  })

  const removePickMutation = useMutation({
    mutationFn: async (id: string) => {
      setRemovingPickId(id)
      await removePick(id)
      return id
    },
    onSuccess: (id) => {
      queryClient.setQueryData<PicksResponse>(PICKS_QUERY_KEY, (current) => ({
        items: (current?.items ?? []).filter((pick) => pick.id !== id),
      }))
    },
    onSettled: () => setRemovingPickId(undefined),
  })

  const clearPicksMutation = useMutation({
    mutationFn: () => clearPicks(),
    onSuccess: () =>
      queryClient.setQueryData<PicksResponse>(PICKS_QUERY_KEY, { items: [] }),
  })

  const reportMutation = useMutation({
    mutationFn: ({
      embed,
      matches,
    }: {
      embed: boolean
      matches: SearchMatch[]
    }) =>
      createReport({
        jobId,
        matches,
        brand: job?.brand?.name || form.brand,
        size: form.size,
        scale: 'CM',
        gender: form.gender,
        embed,
      }),
    onSuccess: setReport,
  })

  const mutationError = useMemo(() => {
    const error =
      searchJobQuery.error ??
      startMutation.error ??
      searchActionMutation.error ??
      addPickMutation.error ??
      removePickMutation.error ??
      clearPicksMutation.error ??
      reportMutation.error
    return error ? errorMessage(error) : undefined
  }, [
    addPickMutation.error,
    clearPicksMutation.error,
    removePickMutation.error,
    reportMutation.error,
    searchJobQuery.error,
    searchActionMutation.error,
    startMutation.error,
  ])

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
      onViewChange={setActiveView}
    >
      {activeView === 'search' ? (
        <>
          <SearchForm
            active={searchActive}
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
            onSubmit={() => startMutation.mutate()}
            onCancel={() => searchActionMutation.mutate('cancel')}
            starting={startMutation.isPending}
          />

          {job ? (
            <SearchStatus
              job={job}
              actionPending={searchActionMutation.isPending}
              onPause={() => searchActionMutation.mutate('pause')}
              onResume={() => searchActionMutation.mutate('resume')}
              onCancel={() => searchActionMutation.mutate('cancel')}
            />
          ) : null}

          {mutationError && !startMutation.error ? (
            <p className="ui-field__error" role="alert">
              {mutationError}
            </p>
          ) : null}

          {job?.matches.length ? (
            <ResultsView
              brand={job.brand?.name || form.brand}
              matches={job.matches}
              picks={picks}
              report={report}
              reporting={reportMutation.isPending}
              savingSpuId={savingSpuId}
              onPick={(match) => addPickMutation.mutate(match)}
              onCreateReport={(matches, embed) =>
                reportMutation.mutate({ matches, embed })
              }
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
          {mutationError ? (
            <p className="ui-field__error" role="alert">
              {mutationError}
            </p>
          ) : null}
          <PicksView
            picks={picks}
            loading={picksQuery.isPending}
            clearing={clearPicksMutation.isPending}
            removingId={removingPickId}
            onRemove={(id) => removePickMutation.mutate(id)}
            onClear={() => clearPicksMutation.mutate()}
          />
        </>
      )}
    </AppShell>
  )
}
