import { AlertTriangle, Ruler, Search, Square } from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useMemo, useState, type FormEvent } from 'react'

import type { Brand, ConversionResponse } from '../api'
import { formatNumber } from '../lib/format'
import type { StoredSearchForm } from '../lib/storage'
import {
  Button,
  Checkbox,
  Field,
  FieldHint,
  FieldLabel,
  Panel,
  Select,
  Switch,
} from './ui'

interface SearchFormProps {
  active: boolean
  brands: Brand[]
  brandsLoading: boolean
  conversion?: ConversionResponse
  conversionLoading: boolean
  error?: string
  form: StoredSearchForm
  onCancel: () => void
  onChange: (next: StoredSearchForm) => void
  onSubmit: () => void
  starting: boolean
}

export function SearchForm({
  active,
  brands,
  brandsLoading,
  conversion,
  conversionLoading,
  error,
  form,
  onCancel,
  onChange,
  onSubmit,
  starting,
}: SearchFormProps) {
  const [showGuide, setShowGuide] = useState(false)
  const reduceMotion = useReducedMotion()
  const revealInitial = reduceMotion
    ? { opacity: 0 }
    : { opacity: 0, height: 0, y: -8 }
  const revealExit = reduceMotion
    ? { opacity: 0 }
    : { opacity: 0, height: 0, y: -5 }
  const revealTransition = {
    duration: reduceMotion ? 0.1 : 0.24,
    ease: [0.22, 1, 0.36, 1] as const,
  }
  const officialBrands = useMemo(() => {
    const seenNames = new Set<string>()
    return brands.filter((brand) => {
      if (!brand.has_official_size_chart) return false
      const normalizedName = brand.name.trim().toLocaleLowerCase('ru-RU')
      if (seenNames.has(normalizedName)) return false
      seenNames.add(normalizedName)
      return true
    })
  }, [brands])
  const suggestedBrands = form.officialBrandsOnly ? officialBrands : brands
  const selectedBrand = useMemo(() => {
    const selectedName = form.brand.trim().toLocaleLowerCase('ru-RU')
    if (!selectedName) return undefined
    return brands.find(
      (brand) => brand.name.toLocaleLowerCase('ru-RU') === selectedName,
    )
  }, [brands, form.brand])
  const convertedSize = conversion?.sizes
  const convertedGrid =
    convertedSize?.gender === 'women' ? 'женская' : 'мужская / унисекс'
  const hasDistinctCmLabel =
    convertedSize?.foot !== undefined &&
    convertedSize.cm !== undefined &&
    Math.abs(convertedSize.foot - convertedSize.cm) > 0.05

  function update<Key extends keyof StoredSearchForm>(
    key: Key,
    value: StoredSearchForm[Key],
  ) {
    onChange({ ...form, [key]: value })
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onSubmit()
  }

  return (
    <Panel tone="raised">
      <form className="search-form ui-card__content" onSubmit={submit}>
        <div className="search-form__primary">
          <Field
            label="Бренд"
            list="brand-options"
            required
            autoComplete="off"
            placeholder="Nike, adidas, New Balance…"
            hint={
              brandsLoading
                ? 'Список подсказок загружается; бренд уже можно ввести вручную.'
                : form.officialBrandsOnly
                  ? `Брендов с официальной сеткой: ${suggestedBrands.length}`
                  : `Доступно подсказок: ${brands.length}`
            }
            value={form.brand}
            onChange={(event) => update('brand', event.target.value)}
          />
          <datalist id="brand-options">
            {suggestedBrands.map((brand) => (
              <option
                key={brand.id}
                value={brand.name}
                label={
                  brand.has_official_size_chart
                    ? `${brand.name} · официальная сетка`
                    : brand.name
                }
              />
            ))}
          </datalist>

          <Field
            label="Длина стопы, см"
            required
            type="number"
            min="15"
            max="40"
            step="0.1"
            inputMode="decimal"
            placeholder="26,5"
            value={form.size}
            hint={
              <>
                Чистый замер без запаса.{' '}
                <button
                  className="inline-link"
                  type="button"
                  aria-expanded={showGuide}
                  aria-controls="measure-guide"
                  onClick={() => setShowGuide((shown) => !shown)}
                >
                  Как измерить
                </button>
              </>
            }
            onChange={(event) => update('size', event.target.value)}
          />

          <div className="ui-field">
            <FieldLabel htmlFor="gender">Размерная сетка</FieldLabel>
            <Select
              id="gender"
              value={form.gender}
              onChange={(event) =>
                update(
                  'gender',
                  event.target.value as StoredSearchForm['gender'],
                )
              }
            >
              <option value="men">Мужская / унисекс</option>
              <option value="women">Женская</option>
            </Select>
            <FieldHint>Уточняет US-размер в таблицах бренда.</FieldHint>
          </div>

          <div className="ui-field">
            <FieldLabel htmlFor="depth">Глубина поиска</FieldLabel>
            <Select
              id="depth"
              value={form.depth}
              onChange={(event) => update('depth', event.target.value)}
            >
              <option value="40">Быстро · 40 моделей</option>
              <option value="120">Глубже · 120 моделей</option>
              <option value="0">Весь каталог</option>
            </Select>
            <FieldHint>Результаты появляются по мере проверки.</FieldHint>
          </div>
        </div>

        <div className="official-brand-filter">
          <Switch
            id="official-brands-only"
            aria-label="Только бренды с официальной размерной сеткой"
            aria-controls="brand-options"
            label="Только бренды с официальной размерной сеткой"
            description="Источник размеров — официальный сайт производителя."
            checked={form.officialBrandsOnly}
            onChange={(event) =>
              update('officialBrandsOnly', event.target.checked)
            }
          />
          <motion.span
            key={`${officialBrands.length}-${brands.length}`}
            className="official-brand-filter__count"
            initial={reduceMotion ? false : { opacity: 0, scale: 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
          >
            {brandsLoading
              ? 'Загружаю…'
              : `${officialBrands.length} из ${brands.length}`}
          </motion.span>
          <AnimatePresence initial={false}>
            {form.officialBrandsOnly &&
            selectedBrand &&
            !selectedBrand.has_official_size_chart ? (
              <motion.p
                className="official-brand-filter__notice"
                role="status"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
              >
                «{selectedBrand.name}» остаётся выбранным, но для него будет
                использована общая размерная сетка.
              </motion.p>
            ) : null}
          </AnimatePresence>
        </div>

        <AnimatePresence initial={false}>
          {showGuide ? (
            <motion.div
              key="measure-guide"
              id="measure-guide"
              className="measure-guide motion-collapse"
              initial={revealInitial}
              animate={{ opacity: 1, height: 'auto', y: 0 }}
              exit={revealExit}
              transition={revealTransition}
            >
              <strong>Как измерить стопу</strong>
              <ol>
                <li>Встаньте пяткой к стене на лист бумаги.</li>
                <li>
                  Отметьте самый дальний палец и измерьте расстояние от края
                  листа.
                </li>
                <li>
                  Измерьте обе ноги вечером и используйте большее значение.
                </li>
              </ol>
              Запас уже заложен производителем — прибавлять его к замеру не
              нужно.
            </motion.div>
          ) : null}
        </AnimatePresence>

        <AnimatePresence initial={false} mode="wait">
          {conversion?.sizes || conversion?.compare.length ? (
            <motion.div
              key="size-preview"
              className="size-preview motion-collapse"
              aria-live="polite"
              initial={revealInitial}
              animate={{ opacity: 1, height: 'auto', y: 0 }}
              exit={revealExit}
              transition={revealTransition}
            >
              <Ruler size={17} aria-hidden="true" />
              {conversion.sizes ? (
                <>
                  <span className="size-preview__main">
                    Ваш размер в {conversion.sizes.brand} ({convertedGrid}{' '}
                    сетка):
                  </span>
                  <motion.span
                    className="size-preview__value"
                    initial={reduceMotion ? false : { scale: 0.82 }}
                    animate={{ scale: 1 }}
                  >
                    EU {formatNumber(conversion.sizes.eu)}
                  </motion.span>
                  <span>
                    US {formatNumber(conversion.sizes.us)} · UK{' '}
                    {formatNumber(conversion.sizes.uk)}
                    {conversion.sizes.foot !== undefined
                      ? ` · стопа ${formatNumber(conversion.sizes.foot)} см`
                      : ''}
                    {conversion.sizes.cm !== undefined &&
                    conversion.sizes.foot === undefined
                      ? ` · CM ${formatNumber(conversion.sizes.cm)} см`
                      : ''}
                    {hasDistinctCmLabel
                      ? ` · маркировка CM/JP ${formatNumber(conversion.sizes.cm)} см`
                      : ''}
                    {!conversion.sizes.exact ? ' · приблизительно' : ''}
                  </span>
                </>
              ) : (
                <span>
                  Для «{form.brand}» точной таблицы нет — используем общую сетку
                  при поиске.
                </span>
              )}
              {conversion.compare.length > 1 ? (
                <div className="size-preview__compare">
                  <span>Для сравнения:</span>
                  {conversion.compare.map((item, index) => (
                    <motion.span
                      key={item.brand}
                      initial={reduceMotion ? false : { opacity: 0, x: -5 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: reduceMotion ? 0 : index * 0.035 }}
                    >
                      {item.brand} EU {formatNumber(item.eu)}
                    </motion.span>
                  ))}
                </div>
              ) : null}
            </motion.div>
          ) : conversionLoading ? (
            <motion.p
              key="size-loading"
              className="ui-field__hint motion-loading-line"
              aria-live="polite"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              Сверяю таблицу размеров…
            </motion.p>
          ) : null}
        </AnimatePresence>

        <AnimatePresence initial={false}>
          {form.depth === '0' ? (
            <motion.div
              key="catalog-warning"
              className="notice motion-collapse"
              initial={revealInitial}
              animate={{ opacity: 1, height: 'auto', y: 0 }}
              exit={revealExit}
              transition={revealTransition}
            >
              <AlertTriangle size={17} aria-hidden="true" />
              <span>
                Весь каталог крупного бренда может занять десятки минут.
                Ограничение цены ускоряет обработку; поиск можно остановить, а
                уже найденные модели сохранятся.
              </span>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <AnimatePresence initial={false}>
          {error ? (
            <motion.p
              key="form-error"
              className="ui-field__error"
              role="alert"
              initial={{ opacity: 0, x: reduceMotion ? 0 : -6 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0 }}
            >
              {error}
            </motion.p>
          ) : null}
        </AnimatePresence>

        <div className="search-form__secondary">
          <Field
            label="Цена до, ₽"
            optionalLabel="необязательно"
            type="number"
            min="0"
            placeholder="Не важно"
            value={form.maxPrice}
            onChange={(event) => update('maxPrice', event.target.value)}
          />

          <div className="ui-field">
            <FieldLabel htmlFor="pace">Темп запросов</FieldLabel>
            <Select
              id="pace"
              value={form.pace}
              onChange={(event) =>
                update('pace', event.target.value as StoredSearchForm['pace'])
              }
            >
              <option value="polite">Бережный</option>
              <option value="normal">Обычный</option>
              <option value="fast">Быстрый · риск лимита</option>
            </Select>
          </div>

          <Checkbox
            label="Добавить детскую обувь"
            description="По умолчанию ищем только взрослые модели."
            checked={form.kids}
            onChange={(event) => update('kids', event.target.checked)}
          />

          <div className="search-form__actions">
            <Button
              type="submit"
              size="lg"
              loading={starting}
              loadingLabel="Запускаю…"
              disabled={active}
            >
              <Search size={17} aria-hidden="true" />
              {active ? 'Ищу…' : 'Найти'}
            </Button>
            {active ? (
              <Button
                type="button"
                size="lg"
                variant="secondary"
                onClick={onCancel}
              >
                <Square size={15} aria-hidden="true" />
                Стоп
              </Button>
            ) : null}
          </div>
        </div>
      </form>
    </Panel>
  )
}
