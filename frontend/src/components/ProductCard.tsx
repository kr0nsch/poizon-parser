import {
  BookmarkCheck,
  BookmarkPlus,
  ChevronDown,
  ExternalLink,
  ImageOff,
  Info,
  Trash2,
} from 'lucide-react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { useId, useState } from 'react'

import type { Pick, PickQuery, SearchMatch } from '../api'
import {
  fitHint,
  formatMoney,
  formatNumber,
  poizonSizeLabel,
  thumbnailUrl,
} from '../lib/format'
import { Badge, Button, Card } from './ui'

const MotionCard = motion.create(Card)

interface ProductCardProps {
  match: SearchMatch
  onPick?: (match: SearchMatch) => void
  onRemove?: (id: string) => void
  pick?: Pick
  picked?: boolean
  query?: PickQuery
  removing?: boolean
  saving?: boolean
}

export function ProductCard({
  match,
  onPick,
  onRemove,
  pick,
  picked = false,
  query,
  removing = false,
  saving = false,
}: ProductCardProps) {
  const image = thumbnailUrl(match.image)
  const fit = fitHint(match.size_tip)
  const savedQuery = query ?? pick?.query
  const shouldReduceMotion = useReducedMotion()
  const [detailsOpen, setDetailsOpen] = useState(false)
  const detailsId = useId()
  const detailsButtonId = `${detailsId}-trigger`
  const revealTransition = shouldReduceMotion
    ? { duration: 0 }
    : { type: 'spring' as const, stiffness: 320, damping: 28, mass: 0.7 }
  const conversionDetails = [
    match.exact_conversion ? 'Точный перевод' : 'Приблизительный перевод',
    match.conversion_note,
  ]
    .filter(Boolean)
    .join(' · ')
  const hasDistinctCmLabel =
    match.converted_foot != null &&
    match.converted_cm != null &&
    Math.abs(match.converted_foot - match.converted_cm) > 0.05

  return (
    <MotionCard
      className="product-card"
      tone="raised"
      whileHover={
        shouldReduceMotion
          ? undefined
          : {
              scale: 1.012,
              y: -4,
              transition: { type: 'spring', stiffness: 420, damping: 30 },
            }
      }
      whileTap={shouldReduceMotion ? undefined : { scale: 0.995 }}
    >
      <div className="product-card__image">
        {image ? (
          <motion.img
            src={image}
            alt=""
            loading="lazy"
            initial={shouldReduceMotion ? false : { opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            whileHover={shouldReduceMotion ? undefined : { scale: 1.035 }}
            transition={revealTransition}
          />
        ) : (
          <ImageOff
            className="product-card__placeholder"
            size={28}
            aria-hidden="true"
          />
        )}
      </div>
      <div className="product-card__content">
        {savedQuery ? (
          <div className="product-card__query">
            <Badge tone="outline">
              {savedQuery.brand} · {savedQuery.size} {savedQuery.scale}
            </Badge>
            {pick?.saved_at ? <Badge>{pick.saved_at}</Badge> : null}
          </div>
        ) : null}

        <h3 className="product-card__title">{match.title}</h3>

        <div className="product-card__query">
          <Badge tone="positive">{poizonSizeLabel(match)}</Badge>
          {fit ? (
            <Badge tone="system" title={match.size_tip}>
              Посадка {fit}
            </Badge>
          ) : null}
          {match.converted_foot != null ? (
            <Badge>Стопа {formatNumber(match.converted_foot)} см</Badge>
          ) : null}
          {match.converted_cm != null &&
          (match.converted_foot == null || hasDistinctCmLabel) ? (
            <Badge>
              {hasDistinctCmLabel ? 'CM/JP' : 'CM'}{' '}
              {formatNumber(match.converted_cm)} см
            </Badge>
          ) : null}
          {!match.exact_conversion ? (
            <Badge
              tone="warning"
              title={match.conversion_note || 'Перевод приблизительный'}
            >
              ≈ перевод
            </Badge>
          ) : null}
        </div>

        <Button
          id={detailsButtonId}
          size="sm"
          variant="quiet"
          aria-expanded={detailsOpen}
          aria-controls={detailsId}
          onClick={() => setDetailsOpen((open) => !open)}
        >
          <Info size={14} aria-hidden="true" />
          Детали
          <motion.span
            aria-hidden="true"
            style={{ display: 'inline-flex' }}
            animate={{ rotate: detailsOpen ? 180 : 0 }}
            transition={
              shouldReduceMotion
                ? { duration: 0 }
                : { type: 'spring', stiffness: 440, damping: 30 }
            }
          >
            <ChevronDown size={14} />
          </motion.span>
        </Button>

        <AnimatePresence initial={false}>
          {detailsOpen ? (
            <motion.div
              id={detailsId}
              role="region"
              aria-labelledby={detailsButtonId}
              initial={
                shouldReduceMotion ? false : { height: 0, opacity: 0, y: -6 }
              }
              animate={{ height: 'auto', opacity: 1, y: 0 }}
              exit={
                shouldReduceMotion
                  ? { display: 'none' }
                  : { height: 0, opacity: 0, y: -4 }
              }
              transition={
                shouldReduceMotion
                  ? { duration: 0 }
                  : { duration: 0.22, ease: [0.22, 1, 0.36, 1] }
              }
              style={{ overflow: 'hidden' }}
            >
              <div className="product-card__query">
                {match.article ? (
                  <Badge tone="outline">Артикул {match.article}</Badge>
                ) : null}
                {match.variant ? (
                  <Badge tone="outline">Вариант {match.variant}</Badge>
                ) : null}
                <Badge
                  tone={match.exact_conversion ? 'system' : 'warning'}
                  title={match.conversion_note || undefined}
                >
                  {conversionDetails}
                </Badge>
                {match.inventory_no ? (
                  <Badge tone="outline">
                    Инвентарный № {match.inventory_no}
                  </Badge>
                ) : null}
              </div>
            </motion.div>
          ) : null}
        </AnimatePresence>

        <div className="product-card__price">
          <strong>{formatMoney(match)}</strong>
          <span className="product-card__delivery">{match.delivery}</span>
        </div>

        <div className="product-card__actions">
          <a
            className="ui-button ui-button--secondary ui-button--sm"
            href={match.url}
            target="_blank"
            rel="noreferrer"
          >
            Открыть
            <ExternalLink size={14} aria-hidden="true" />
          </a>
          {pick ? (
            <Button
              size="sm"
              variant="quiet"
              loading={removing}
              loadingLabel="Убираю…"
              onClick={() => onRemove?.(pick.id)}
              aria-label={`Убрать ${match.title} из итогов`}
            >
              <Trash2 size={14} aria-hidden="true" />
              Убрать
            </Button>
          ) : (
            <Button
              size="sm"
              variant={picked ? 'system' : 'primary'}
              disabled={picked}
              loading={saving}
              onClick={() => onPick?.(match)}
            >
              {picked ? (
                <BookmarkCheck size={14} aria-hidden="true" />
              ) : (
                <BookmarkPlus size={14} aria-hidden="true" />
              )}
              {picked ? 'В итогах' : 'В итоги'}
            </Button>
          )}
        </div>
      </div>
    </MotionCard>
  )
}
