import { useQuery } from '@tanstack/react-query'

import {
  ApiError,
  getSearchJob,
  isTerminalSearchStatus,
  type SearchSnapshot,
} from '../api'

export const SEARCH_JOB_POLL_INTERVAL_MS = 1_000

export const searchJobQueryKey = (jobId: string | null | undefined) =>
  ['search-job', jobId ?? null] as const

export interface UseSearchJobOptions {
  enabled?: boolean
  pollIntervalMs?: number
}

export function useSearchJob(
  jobId: string | null | undefined,
  options: UseSearchJobOptions = {},
) {
  const normalizedJobId = jobId?.trim() || null
  const pollIntervalMs = options.pollIntervalMs ?? SEARCH_JOB_POLL_INTERVAL_MS

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

      return getSearchJob(normalizedJobId, { signal })
    },
    enabled: (options.enabled ?? true) && normalizedJobId !== null,
    refetchInterval: (query) => {
      const snapshot = query.state.data
      if (snapshot && isTerminalSearchStatus(snapshot.status)) {
        return false
      }
      const error = query.state.error
      if (error && error.status >= 400 && error.status < 500) {
        return false
      }

      return pollIntervalMs > 0 ? pollIntervalMs : false
    },
    refetchIntervalInBackground: false,
    retry: (failureCount, error) => {
      if (error.status >= 400 && error.status < 500) {
        return false
      }

      return failureCount < 2
    },
  })
}
