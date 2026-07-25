import {
  BookmarkCheck,
  BookmarkPlus,
  ExternalLink,
  ImageOff,
  Trash2,
} from 'lucide-react'

import type { Pick, PickQuery, SearchMatch } from '../api'
import {
  fitHint,
  formatMoney,
  poizonSizeLabel,
  thumbnailUrl,
} from '../lib/format'
import { Badge, Button, Card } from './ui'

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

  return (
    <Card className="product-card" tone="raised">
      <div className="product-card__image">
        {image ? (
          <img src={image} alt="" loading="lazy" />
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
          {match.converted_cm ? (
            <Badge>Ярлык {match.converted_cm} см</Badge>
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
    </Card>
  )
}
