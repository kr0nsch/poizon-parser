import { requestJson, requestJsonBody } from './client'
import type {
  AddPickRequest,
  AddPickResponse,
  BrandsResponse,
  ClearPicksResponse,
  ConversionRequest,
  ConversionResponse,
  PicksResponse,
  ReportRequest,
  ReportResponse,
  SearchActionResponse,
  SearchRequest,
  SearchSnapshot,
  StartSearchResponse,
} from './types'

export * from './client'
export * from './types'

export interface ApiRequestOptions {
  signal?: AbortSignal
}

const API_ROOT = '/api'

function apiPath(path: string): string {
  return `${API_ROOT}${path}`
}

function resourceId(value: string): string {
  return encodeURIComponent(value)
}

export function getBrands(
  options: ApiRequestOptions = {},
): Promise<BrandsResponse> {
  return requestJson<BrandsResponse>(apiPath('/brands'), {
    signal: options.signal,
  })
}

export function convertSize(
  request: ConversionRequest,
  options: ApiRequestOptions = {},
): Promise<ConversionResponse> {
  const query = new URLSearchParams({
    foot: String(request.foot),
    gender: request.gender ?? 'men',
  })

  if (request.brand) {
    query.set('brand', request.brand)
  }

  return requestJson<ConversionResponse>(
    `${apiPath('/convert')}?${query.toString()}`,
    { signal: options.signal },
  )
}

export function startSearch(
  request: SearchRequest,
  options: ApiRequestOptions = {},
): Promise<StartSearchResponse> {
  return requestJsonBody<StartSearchResponse, SearchRequest>(
    apiPath('/search'),
    request,
    {
      method: 'POST',
      signal: options.signal,
    },
  )
}

export function getSearchJob(
  jobId: string,
  options: ApiRequestOptions = {},
): Promise<SearchSnapshot> {
  return requestJson<SearchSnapshot>(apiPath(`/search/${resourceId(jobId)}`), {
    signal: options.signal,
  })
}

export function cancelSearch(
  jobId: string,
  options: ApiRequestOptions = {},
): Promise<SearchActionResponse> {
  return requestJson<SearchActionResponse>(
    apiPath(`/search/${resourceId(jobId)}/cancel`),
    {
      method: 'POST',
      signal: options.signal,
    },
  )
}

export function pauseSearch(
  jobId: string,
  options: ApiRequestOptions = {},
): Promise<SearchActionResponse> {
  return requestJson<SearchActionResponse>(
    apiPath(`/search/${resourceId(jobId)}/pause`),
    {
      method: 'POST',
      signal: options.signal,
    },
  )
}

export function resumeSearch(
  jobId: string,
  options: ApiRequestOptions = {},
): Promise<SearchActionResponse> {
  return requestJson<SearchActionResponse>(
    apiPath(`/search/${resourceId(jobId)}/continue`),
    {
      method: 'POST',
      signal: options.signal,
    },
  )
}

export function getPicks(
  options: ApiRequestOptions = {},
): Promise<PicksResponse> {
  return requestJson<PicksResponse>(apiPath('/picks'), {
    signal: options.signal,
  })
}

export function addPick(
  request: AddPickRequest,
  options: ApiRequestOptions = {},
): Promise<AddPickResponse> {
  return requestJsonBody<AddPickResponse, AddPickRequest>(
    apiPath('/picks'),
    request,
    {
      method: 'POST',
      signal: options.signal,
    },
  )
}

export function removePick(
  pickId: string,
  options: ApiRequestOptions = {},
): Promise<SearchActionResponse> {
  return requestJson<SearchActionResponse>(
    apiPath(`/picks/${resourceId(pickId)}`),
    {
      method: 'DELETE',
      signal: options.signal,
    },
  )
}

export function clearPicks(
  options: ApiRequestOptions = {},
): Promise<ClearPicksResponse> {
  return requestJson<ClearPicksResponse>(apiPath('/picks'), {
    method: 'DELETE',
    signal: options.signal,
  })
}

export function createReport(
  request: ReportRequest,
  options: ApiRequestOptions = {},
): Promise<ReportResponse> {
  return requestJsonBody<ReportResponse, ReportRequest>(
    apiPath('/report'),
    request,
    {
      method: 'POST',
      signal: options.signal,
    },
  )
}
