import {
  AlertTriangle,
  Bookmark,
  Download,
  LoaderCircle,
  RotateCw,
  Trash2,
} from 'lucide-react'
import {
  AnimatePresence,
  LayoutGroup,
  motion,
  useReducedMotion,
} from 'motion/react'
import { useRef } from 'react'

import type { Pick } from '../api'
import { downloadText, rowsToCsv } from '../lib/download'
import { poizonSizeLabel } from '../lib/format'
import { useFocusRescue, useListFocusRescue } from '../lib/utils'
import { EmptyState } from './EmptyState'
import { ProductCard } from './ProductCard'
import { Button } from './ui'

interface PicksViewProps {
  clearing: boolean
  /** Итоги не загрузились: пустой список тогда не значит «пусто». */
  error?: string
  loading: boolean
  onClear: () => void
  onRemove: (id: string) => void
  onRetry: () => void
  picks: Pick[]
  /** id позиций, которые сейчас удаляются. */
  removingIds: ReadonlySet<string>
  retrying?: boolean
}

export function PicksView({
  clearing,
  error,
  loading,
  onClear,
  onRemove,
  onRetry,
  picks,
  removingIds,
  retrying = false,
}: PicksViewProps) {
  const reduceMotion = useReducedMotion()
  // Убранная карточка уносит фокус с собой: он переходит на то же действие
  // соседней карточки, а если итоги опустели — на пустое состояние.
  const emptyRef = useRef<HTMLDivElement>(null)
  const titleRef = useRef<HTMLSpanElement>(null)
  const rescueCardFocus = useListFocusRescue<HTMLDivElement>(
    () => emptyRef.current ?? titleRef.current,
  )
  const rescueClearFocus = useFocusRescue<HTMLButtonElement>(
    () => emptyRef.current,
  )
  // Удачный повтор убирает сообщение об ошибке вместе с «Повторить»: фокус
  // уходит на загруженные итоги (счётчик) или на пустое состояние.
  const rescueRetryFocus = useFocusRescue<HTMLButtonElement>(
    () => emptyRef.current ?? titleRef.current,
  )

  function exportJson() {
    downloadText(
      'poizon-picks.json',
      JSON.stringify(picks, null, 2),
      'application/json',
    )
  }

  function exportCsv() {
    const rows = picks.map((pick) => [
      pick.match.title,
      pick.match.brand,
      `${pick.query.size} ${pick.query.scale}`,
      poizonSizeLabel(pick.match),
      pick.match.price,
      pick.match.delivery,
      pick.match.url,
      pick.saved_at,
    ])
    downloadText(
      'poizon-picks.csv',
      rowsToCsv([
        [
          'Модель',
          'Бренд',
          'Запрос',
          'Размер на POIZON',
          'Цена, ₽',
          'Доставка',
          'Ссылка',
          'Сохранено',
        ],
        ...rows,
      ]),
      'text/csv;charset=utf-8',
    )
  }

  function confirmClear() {
    if (window.confirm('Удалить все сохранённые позиции?')) onClear()
  }

  if (loading) {
    return (
      <div className="empty-state" aria-live="polite">
        <div>
          <span className="empty-state__icon">
            <LoaderCircle className="ui-button__spinner" size={24} />
          </span>
          <h2>Загружаю итоги</h2>
        </div>
      </div>
    )
  }

  const retryButton = (
    <Button
      ref={rescueRetryFocus}
      size="sm"
      variant="secondary"
      loading={retrying}
      loadingLabel="Загружаю…"
      onClick={onRetry}
    >
      <RotateCw size={14} aria-hidden="true" />
      Повторить
    </Button>
  )

  if (error && picks.length === 0) {
    return (
      <div className="empty-state" role="alert">
        <div>
          <span className="empty-state__icon" aria-hidden="true">
            <AlertTriangle size={24} />
          </span>
          <h2>Не удалось загрузить итоги</h2>
          <p>{error}</p>
          <div style={{ marginTop: '0.9rem' }}>{retryButton}</div>
        </div>
      </div>
    )
  }

  if (picks.length === 0) {
    return (
      <EmptyState
        ref={emptyRef}
        icon={Bookmark}
        title="В итогах пока пусто"
        description="Добавляйте подходящие модели из поиска. Подборка сохраняется локально для этого браузера и переживает перезапуск сервера."
      />
    )
  }

  return (
    <section aria-labelledby="picks-title">
      {error ? (
        <div className="notice" role="alert" style={{ marginBottom: '0.8rem' }}>
          <AlertTriangle size={17} aria-hidden="true" />
          <span style={{ flex: 1 }}>
            Не удалось обновить итоги — показана последняя загруженная версия.{' '}
            {error}
          </span>
          {retryButton}
        </div>
      ) : null}
      <div className="picks-toolbar">
        <span
          ref={titleRef}
          className="picks-toolbar__count"
          id="picks-title"
          tabIndex={-1}
        >
          Сохранено позиций: <strong>{picks.length}</strong>
        </span>
        <Button size="sm" variant="secondary" onClick={exportCsv}>
          <Download size={14} aria-hidden="true" />
          CSV
        </Button>
        <Button size="sm" variant="secondary" onClick={exportJson}>
          JSON
        </Button>
        <Button
          ref={rescueClearFocus}
          size="sm"
          variant="quiet"
          loading={clearing}
          onClick={confirmClear}
        >
          <Trash2 size={14} aria-hidden="true" />
          Очистить всё
        </Button>
      </div>

      <LayoutGroup id="saved-products">
        <div className="product-grid">
          <AnimatePresence mode="popLayout">
            {picks.map((pick, index) => (
              <motion.div
                key={pick.id}
                ref={rescueCardFocus}
                className="product-card-slot"
                layout="position"
                initial={
                  reduceMotion
                    ? { opacity: 0 }
                    : { opacity: 0, y: 8, scale: 0.99 }
                }
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={
                  reduceMotion
                    ? { opacity: 0 }
                    : { opacity: 0, x: 12, scale: 0.985 }
                }
                transition={{
                  duration: reduceMotion ? 0.08 : 0.24,
                  delay: reduceMotion || index >= 10 ? 0 : index * 0.025,
                  ease: [0.22, 1, 0.36, 1],
                }}
              >
                <ProductCard
                  pick={pick}
                  match={pick.match}
                  removing={removingIds.has(pick.id)}
                  onRemove={onRemove}
                />
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </LayoutGroup>
    </section>
  )
}
