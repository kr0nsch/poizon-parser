import { useQuery } from '@tanstack/react-query'

import {
  ApiError,
  getSearchJob,
  isTerminalSearchStatus,
  type SearchSnapshot,
} from '../api'

export const SEARCH_JOB_POLL_INTERVAL_MS = 1_000

/** Пауза перед повторным чтением неполного финального снимка. */
export const FINAL_SNAPSHOT_RECHECK_MS = 200

export const searchJobQueryKey = (jobId: string | null | undefined) =>
  ['search-job', jobId ?? null] as const

/** 4xx: задачи на сервере нет или запрос неверен — повтор не поможет. */
export function isPermanentPollError(error: ApiError | null): boolean {
  return error != null && error.status >= 400 && error.status < 500
}

function wait(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(signal.reason)
      return
    }
    const onAbort = () => {
      window.clearTimeout(timer)
      reject(signal.reason)
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

/**
 * Читает снимок задачи. На первом финальном статусе опрос останавливается,
 * поэтому финальный снимок без времени завершения (старый сервер публиковал
 * статус раньше остальных полей) дочитываем ещё один раз.
 */
export async function fetchSearchSnapshot(
  jobId: string,
  signal: AbortSignal,
): Promise<SearchSnapshot> {
  const snapshot = await getSearchJob(jobId, { signal })
  if (
    !isTerminalSearchStatus(snapshot.status) ||
    snapshot.finished_at != null
  ) {
    return snapshot
  }
  await wait(FINAL_SNAPSHOT_RECHECK_MS, signal)
  return getSearchJob(jobId, { signal })
}

export function useSearchJob(jobId: string | null | undefined) {
  const normalizedJobId = jobId?.trim() || null

  return useQuery<SearchSnapshot, ApiError>({
    queryKey: searchJobQueryKey(normalizedJobId),
    queryFn: ({ signal }) => {
      if (normalizedJobId === null) {
        throw new ApiError('Не указан идентификатор задачи', {
          status: 0,
          statusText: 'Invalid job id',
          url: '/api/search',
        })
      }

      return fetchSearchSnapshot(normalizedJobId, signal)
    },
    enabled: normalizedJobId !== null,
    refetchInterval: (query) => {
      const snapshot = query.state.data
      if (snapshot && isTerminalSearchStatus(snapshot.status)) {
        return false
      }
      if (isPermanentPollError(query.state.error)) {
        return false
      }

      return SEARCH_JOB_POLL_INTERVAL_MS
    },
    refetchIntervalInBackground: false,
    retry: (failureCount, error) => {
      if (isPermanentPollError(error)) {
        return false
      }

      return failureCount < 2
    },
  })
}
