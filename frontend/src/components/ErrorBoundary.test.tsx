import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FORM_STORAGE_KEY } from '../lib/storage'
import { ErrorBoundary } from './ErrorBoundary'

function Crash(): never {
  throw new Error('form.brand.trim is not a function')
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    localStorage.clear()
    // React и сам ErrorBoundary пишут пойманную ошибку в консоль.
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
  })

  afterEach(() => vi.restoreAllMocks())

  it('renders children while nothing fails', () => {
    render(
      <ErrorBoundary>
        <p>всё хорошо</p>
      </ErrorBoundary>,
    )

    expect(screen.getByText('всё хорошо')).toBeInTheDocument()
  })

  it('offers to reset saved settings instead of a white screen', async () => {
    const user = userEvent.setup()
    const onReload = vi.fn()
    localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify({ brand: null }))

    render(
      <ErrorBoundary onReload={onReload}>
        <Crash />
      </ErrorBoundary>,
    )

    expect(
      screen.getByText('Интерфейс не смог загрузиться'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('form.brand.trim is not a function'),
    ).toBeInTheDocument()

    await user.click(
      screen.getByRole('button', {
        name: 'Сбросить сохранённые настройки и перезагрузить',
      }),
    )

    expect(localStorage.getItem(FORM_STORAGE_KEY)).toBeNull()
    expect(onReload).toHaveBeenCalledOnce()
  })

  it('can reload without touching saved settings', async () => {
    const user = userEvent.setup()
    const onReload = vi.fn()
    localStorage.setItem(FORM_STORAGE_KEY, '{"brand":"Nike"}')

    render(
      <ErrorBoundary onReload={onReload}>
        <Crash />
      </ErrorBoundary>,
    )
    await user.click(
      screen.getByRole('button', { name: 'Просто перезагрузить' }),
    )

    expect(localStorage.getItem(FORM_STORAGE_KEY)).toBe('{"brand":"Nike"}')
    expect(onReload).toHaveBeenCalledOnce()
  })
})
