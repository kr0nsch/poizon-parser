import { AlertTriangle, RotateCw } from 'lucide-react'
import { Component, type ErrorInfo, type ReactNode } from 'react'

import { resetSavedSettings } from '../lib/storage'
import { Button } from './ui'

interface ErrorBoundaryProps {
  children: ReactNode
  /** Перезагрузка страницы; в тестах подменяется. */
  onReload?: () => void
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * Последний рубеж: ошибка при отрисовке не оставляет белый экран, а
 * предлагает сбросить сохранённые настройки — частая причина падения на
 * каждой загрузке.
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: unknown): ErrorBoundaryState {
    return { error: error instanceof Error ? error : new Error(String(error)) }
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('Интерфейс упал при отрисовке', error, info.componentStack)
  }

  private reload = () => {
    if (this.props.onReload) this.props.onReload()
    else window.location.reload()
  }

  private resetAndReload = () => {
    resetSavedSettings()
    this.reload()
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    return (
      <div
        className="ui-page"
        style={{ display: 'grid', placeItems: 'center', padding: '1rem' }}
      >
        <div
          className="empty-state"
          role="alert"
          style={{ width: '100%', maxWidth: '40rem' }}
        >
          <div>
            <span className="empty-state__icon" aria-hidden="true">
              <AlertTriangle size={24} />
            </span>
            <h2>Интерфейс не смог загрузиться</h2>
            <p>
              Чаще всего причина — повреждённые сохранённые настройки формы.
              Сбросьте их: подборка в «Итогах» хранится на сервере и не
              пострадает.
            </p>
            <p>
              <code>{error.message}</code>
            </p>
            <div
              className="ui-cluster"
              style={{ justifyContent: 'center', marginTop: '1rem' }}
            >
              <Button onClick={this.resetAndReload}>
                <RotateCw size={15} aria-hidden="true" />
                Сбросить сохранённые настройки и перезагрузить
              </Button>
              <Button variant="secondary" onClick={this.reload}>
                Просто перезагрузить
              </Button>
            </div>
          </div>
        </div>
      </div>
    )
  }
}
