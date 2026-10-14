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

  const error = (value as Record<string, unknown>).error
  return typeof error === 'string' && error.trim().length > 0
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

/**
 * Понятный текст для ответа без собственного сообщения сервера (например,
 * Vite-прокси, когда Python-сервер не запущен).
 */
export function statusMessage(status: number, statusText = ''): string {
  if (status === 400)
    return 'Сервер отклонил запрос: проверьте введённые данные.'
  if (status === 403) return 'Сервер отклонил запрос: доступ запрещён.'
  if (status === 404) {
    return 'Не найдено: возможно, сервер перезапускался и данные на странице устарели.'
  }
  if (status === 409) {
    return 'Действие сейчас недоступно: состояние уже изменилось. Обновите данные и попробуйте снова.'
  }
  if (status === 413) return 'Запрос слишком большой для сервера.'
  if (status === 502 || status === 503 || status === 504) {
    return 'Сервер недоступен. Проверьте, что локальный сервер запущен, и попробуйте ещё раз.'
  }
  if (status >= 500) {
    return 'Внутренняя ошибка сервера — подробности в консоли, где он запущен.'
  }
  return `Ошибка API: ${status} ${statusText}`.trim()
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
  let parseError: unknown
  let invalidJson = false

  if (text.length > 0) {
    try {
      body = JSON.parse(text) as unknown
    } catch (cause) {
      body = text
      parseError = cause
      invalidJson = true
    }
  }

  if (!response.ok) {
    // Ответ об ошибке не обязан быть JSON (прокси, обрыв): тогда объясняем
    // по статусу, а не жалуемся на формат.
    const message = isApiErrorBody(body)
      ? body.error
      : statusMessage(response.status, response.statusText)

    throw new ApiError(message, {
      status: response.status,
      statusText: response.statusText,
      url: response.url || url,
      body,
      cause: parseError,
    })
  }

  if (invalidJson) {
    throw new ApiError('Сервер вернул некорректный JSON', {
      status: response.status,
      statusText: response.statusText,
      url: response.url || url,
      body,
      cause: parseError,
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
