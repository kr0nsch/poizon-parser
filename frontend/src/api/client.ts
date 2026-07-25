export interface ApiErrorDetails {
  status: number
  statusText: string
  url: string
  body?: unknown
  cause?: unknown
}

export interface ApiErrorBody {
  error: string
}

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null) return false

  return (
    'error' in value &&
    typeof (value as Record<string, unknown>).error === 'string'
  )
}

export class ApiError extends Error {
  readonly status: number
  readonly statusText: string
  readonly url: string
  readonly body: unknown

  constructor(message: string, details: ApiErrorDetails) {
    super(message, { cause: details.cause })
    this.name = 'ApiError'
    this.status = details.status
    this.statusText = details.statusText
    this.url = details.url
    this.body = details.body
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

export async function requestJson<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers)
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json')
  }

  let response: Response
  try {
    response = await fetch(url, {
      credentials: 'same-origin',
      ...init,
      headers,
    })
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      throw cause
    }

    throw new ApiError('Не удалось связаться с сервером', {
      status: 0,
      statusText: 'Network Error',
      url,
      cause,
    })
  }

  const text = await response.text()
  let body: unknown

  if (text.length > 0) {
    try {
      body = JSON.parse(text) as unknown
    } catch (cause) {
      throw new ApiError('Сервер вернул некорректный JSON', {
        status: response.status,
        statusText: response.statusText,
        url: response.url || url,
        body: text,
        cause,
      })
    }
  }

  if (!response.ok) {
    const message = isApiErrorBody(body)
      ? body.error
      : `Ошибка API: ${response.status} ${response.statusText}`.trim()

    throw new ApiError(message, {
      status: response.status,
      statusText: response.statusText,
      url: response.url || url,
      body,
    })
  }

  return body as T
}

export function requestJsonBody<TResponse, TBody>(
  url: string,
  body: TBody,
  init: Omit<RequestInit, 'body'> = {},
): Promise<TResponse> {
  const headers = new Headers(init.headers)
  headers.set('Content-Type', 'application/json')

  return requestJson<TResponse>(url, {
    ...init,
    headers,
    body: JSON.stringify(body),
  })
}
