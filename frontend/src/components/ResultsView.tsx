import {
  Download,
  ExternalLink,
  FileText,
  FilterX,
  SearchX,
  X,
} from 'lucide-react'
import {
  AnimatePresence,
  LayoutGroup,
  motion,
  useReducedMotion,
} from 'motion/react'
import { useMemo, useState } from 'react'

import type { Pick, ReportResponse, SearchMatch } from '../api'
import { downloadText, rowsToCsv } from '../lib/download'
import { deliveryDays, poizonSizeLabel, slugify } from '../lib/format'
import { EmptyState } from './EmptyState'
import { ProductCard } from './ProductCard'
import { Button, Checkbox, Field, Select, Switch } from './ui'

type SortMode = 'priceAsc' | 'priceDesc' | 'fastest' | 'order'

interface ResultsViewProps {
  brand: string
  matches: SearchMatch[]
  onCreateReport: (matches: SearchMatch[], embed: boolean) => void
  onPick: (match: SearchMatch) => void
  picks: Pick[]
  report?: ReportResponse
  reporting: boolean
  savingSpuId?: number
}

function pickKey(match: SearchMatch): string {
  return [
    match.spu_id,
    match.sku_id,
    match.requested_scale,
    match.requested_size,
  ].join('|')
}

export function ResultsView({
  brand,
  matches,
  onCreateReport,
  onPick,
  picks,
  report,
  reporting,
  savingSpuId,
}: ResultsViewProps) {
  const reduceMotion = useReducedMotion()
  const [sort, setSort] = useState<SortMode>('priceAsc')
  const [text, setText] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [exactOnly, setExactOnly] = useState(false)
  const [fastOnly, setFastOnly] = useState(false)
  const [embed, setEmbed] = useState(false)

  const pickedKeys = useMemo(
    () => new Set(picks.map((pick) => pickKey(pick.match))),
    [picks],
  )

  const filtered = useMemo(() => {
    const needle = text.trim().toLocaleLowerCase('ru-RU')
    const maximum = maxPrice ? Number(maxPrice) : null
    const list = matches.filter((match) => {
      if (needle && !match.title.toLocaleLowerCase('ru-RU').includes(needle))
        return false
      if (
        maximum != null &&
        (match.price ?? Number.POSITIVE_INFINITY) > maximum
      )
        return false
      if (exactOnly && !match.exact_conversion) return false
      if (fastOnly && deliveryDays(match.delivery) > 10) return false
      return true
    })

    if (sort === 'priceAsc') {
      list.sort(
        (a, b) =>
          (a.price ?? Number.POSITIVE_INFINITY) -
          (b.price ?? Number.POSITIVE_INFINITY),
      )
    } else if (sort === 'priceDesc') {
      list.sort(
        (a, b) =>
          (b.price ?? Number.NEGATIVE_INFINITY) -
          (a.price ?? Number.NEGATIVE_INFINITY),
      )
    } else if (sort === 'fastest') {
      list.sort((a, b) => deliveryDays(a.delivery) - deliveryDays(b.delivery))
    }
    return list
  }, [exactOnly, fastOnly, matches, maxPrice, sort, text])

  const filtersActive = Boolean(text || maxPrice || exactOnly || fastOnly)

  function resetFilters() {
    setText('')
    setMaxPrice('')
    setExactOnly(false)
    setFastOnly(false)
  }

  function exportResults(kind: 'csv' | 'json') {
    if (filtered.length === 0) return
    const filename = `poizon-${slugify(brand)}`
    if (kind === 'json') {
      downloadText(
        `${filename}.json`,
        JSON.stringify(filtered, null, 2),
        'application/json',
      )
      return
    }
    const rows = filtered.map((match) => [
      match.title,
      poizonSizeLabel(match),
      match.converted_eu,
      match.converted_foot,
      match.converted_cm,
      match.price,
      match.delivery,
      match.url,
    ])
    downloadText(
      `${filename}.csv`,
      rowsToCsv([
        [
          'Модель',
          'Размер на POIZON',
          'EU',
          'Стопа, см',
          'CM/JP, см',
          'Цена, ₽',
          'Доставка',
          'Ссылка',
        ],
        ...rows,
      ]),
      'text/csv;charset=utf-8',
    )
  }

  return (
    <section aria-labelledby="results-title">
      <div className="section-heading">
        <div>
          <h2 id="results-title">Найдено моделей: {matches.length}</h2>
          <p>Фильтры и сортировка применяются и к выгрузке, и к HTML-отчёту.</p>
        </div>
        <div className="toolbar">
          <Button
            size="sm"
            variant="system"
            loading={reporting}
            loadingLabel="Готовлю…"
            onClick={() => onCreateReport(filtered, embed)}
          >
            <FileText size={14} aria-hidden="true" />
            HTML-отчёт
          </Button>
          <Switch
            label="Фото офлайн"
            title="Вшить изображения в HTML-файл"
            checked={embed}
            onChange={(event) => setEmbed(event.target.checked)}
          />
          <Button
            size="sm"
            variant="secondary"
            onClick={() => exportResults('csv')}
          >
            <Download size={14} aria-hidden="true" />
            CSV
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => exportResults('json')}
          >
            JSON
          </Button>
          <Select
            aria-label="Сортировка результатов"
            value={sort}
            onChange={(event) => setSort(event.target.value as SortMode)}
          >
            <option value="priceAsc">Сначала дешевле</option>
            <option value="priceDesc">Сначала дороже</option>
            <option value="fastest">Быстрая доставка</option>
            <option value="order">Порядок каталога</option>
          </Select>
        </div>
      </div>

      {report ? (
        <div className="report-ready" role="status">
          <strong>Отчёт готов</strong>
          <a
            className="ui-button ui-button--system ui-button--sm"
            href={report.view}
            target="_blank"
            rel="noreferrer"
          >
            Открыть
            <ExternalLink size={14} aria-hidden="true" />
          </a>
          <a
            className="ui-button ui-button--secondary ui-button--sm"
            href={report.view}
            download
          >
            Скачать файл
          </a>
          <code>Сохранён в: {report.file}</code>
        </div>
      ) : null}

      <div className="filters-bar">
        <Field
          aria-label="Фильтр по названию"
          label={<span className="ui-sr-only">Фильтр по названию</span>}
          type="search"
          placeholder="Название модели…"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Field
          aria-label="Максимальная цена"
          label={<span className="ui-sr-only">Максимальная цена</span>}
          type="number"
          min="0"
          placeholder="До, ₽"
          value={maxPrice}
          onChange={(event) => setMaxPrice(event.target.value)}
        />
        <Checkbox
          label="Точный перевод"
          checked={exactOnly}
          onChange={(event) => setExactOnly(event.target.checked)}
        />
        <Checkbox
          label="До 10 дней"
          checked={fastOnly}
          onChange={(event) => setFastOnly(event.target.checked)}
        />
        {filtersActive ? (
          <Button size="sm" variant="quiet" onClick={resetFilters}>
            <FilterX size={14} aria-hidden="true" />
            Сбросить
          </Button>
        ) : null}
        <span className="filters-bar__count">
          Показано{' '}
          <motion.strong
            key={filtered.length}
            initial={reduceMotion ? false : { opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
          >
            {filtered.length}
          </motion.strong>{' '}
          из {matches.length}
        </span>
      </div>

      <AnimatePresence initial={false}>
        {filtersActive ? (
          <motion.div
            className="active-filters"
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            aria-label="Активные фильтры"
          >
            <AnimatePresence mode="popLayout">
              {text ? (
                <motion.button
                  key="text-filter"
                  className="filter-chip"
                  type="button"
                  layout
                  exit={{ opacity: 0, scale: 0.9 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setText('')}
                  aria-label={`Убрать фильтр по названию: ${text}`}
                >
                  Название: «{text}»
                  <X size={12} aria-hidden="true" />
                </motion.button>
              ) : null}
              {maxPrice ? (
                <motion.button
                  key="price-filter"
                  className="filter-chip"
                  type="button"
                  layout
                  exit={{ opacity: 0, scale: 0.9 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setMaxPrice('')}
                  aria-label={`Убрать ограничение цены до ${maxPrice} рублей`}
                >
                  До {maxPrice} ₽
                  <X size={12} aria-hidden="true" />
                </motion.button>
              ) : null}
              {exactOnly ? (
                <motion.button
                  key="exact-filter"
                  className="filter-chip"
                  type="button"
                  layout
                  exit={{ opacity: 0, scale: 0.9 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setExactOnly(false)}
                  aria-label="Убрать фильтр точного перевода"
                >
                  Точный перевод
                  <X size={12} aria-hidden="true" />
                </motion.button>
              ) : null}
              {fastOnly ? (
                <motion.button
                  key="fast-filter"
                  className="filter-chip"
                  type="button"
                  layout
                  exit={{ opacity: 0, scale: 0.9 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setFastOnly(false)}
                  aria-label="Убрать фильтр доставки до десяти дней"
                >
                  До 10 дней
                  <X size={12} aria-hidden="true" />
                </motion.button>
              ) : null}
            </AnimatePresence>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {filtered.length > 0 ? (
        <LayoutGroup id="search-results">
          <div className="product-grid">
            <AnimatePresence initial={false} mode="popLayout">
              {filtered.map((match, index) => (
                <motion.div
                  key={`${match.spu_id}-${match.sku_id}`}
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
                      : { opacity: 0, y: 5, scale: 0.985 }
                  }
                  transition={{
                    duration: reduceMotion ? 0.08 : 0.24,
                    delay: reduceMotion || index >= 12 ? 0 : index * 0.025,
                    ease: [0.22, 1, 0.36, 1],
                  }}
                >
                  <ProductCard
                    match={match}
                    picked={pickedKeys.has(pickKey(match))}
                    saving={savingSpuId === match.spu_id}
                    onPick={onPick}
                  />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </LayoutGroup>
      ) : (
        <div style={{ marginTop: '0.9rem' }}>
          <EmptyState
            icon={SearchX}
            title="По этим фильтрам ничего нет"
            description="Сбросьте часть фильтров — исходные результаты поиска остаются на месте."
          />
        </div>
      )}
    </section>
  )
}
