import { Bookmark, Download, LoaderCircle, Trash2 } from 'lucide-react'

import type { Pick } from '../api'
import { downloadText, rowsToCsv } from '../lib/download'
import { poizonSizeLabel } from '../lib/format'
import { EmptyState } from './EmptyState'
import { ProductCard } from './ProductCard'
import { Button } from './ui'

interface PicksViewProps {
  clearing: boolean
  loading: boolean
  onClear: () => void
  onRemove: (id: string) => void
  picks: Pick[]
  removingId?: string
}

export function PicksView({
  clearing,
  loading,
  onClear,
  onRemove,
  picks,
  removingId,
}: PicksViewProps) {
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

  if (picks.length === 0) {
    return (
      <EmptyState
        icon={Bookmark}
        title="В итогах пока пусто"
        description="Добавляйте подходящие модели из поиска. Подборка сохраняется локально для этого браузера и переживает перезапуск сервера."
      />
    )
  }

  return (
    <section aria-labelledby="picks-title">
      <div className="picks-toolbar">
        <span className="picks-toolbar__count" id="picks-title">
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
          size="sm"
          variant="quiet"
          loading={clearing}
          onClick={confirmClear}
        >
          <Trash2 size={14} aria-hidden="true" />
          Очистить всё
        </Button>
      </div>

      <div className="product-grid">
        {picks.map((pick) => (
          <ProductCard
            key={pick.id}
            pick={pick}
            match={pick.match}
            removing={removingId === pick.id}
            onRemove={onRemove}
          />
        ))}
      </div>
    </section>
  )
}
