import { useId, type ComponentPropsWithRef, type ReactNode } from 'react'

import { cn } from '../../lib/utils'

export type ProgressTone = 'primary' | 'system' | 'warning' | 'danger'

export interface ProgressProps extends Omit<
  ComponentPropsWithRef<'progress'>,
  'children' | 'max' | 'value'
> {
  containerClassName?: string
  formatValue?: (value: number, max: number) => ReactNode
  label?: ReactNode
  max?: number
  showValue?: boolean
  tone?: ProgressTone
  value?: number | null
}

export function Progress({
  'aria-label': ariaLabel,
  'aria-labelledby': ariaLabelledBy,
  className,
  containerClassName,
  formatValue,
  id,
  label,
  max = 100,
  showValue = false,
  tone = 'primary',
  value,
  ...props
}: ProgressProps) {
  const generatedId = useId()
  const progressId = id ?? `progress-${generatedId}`
  const hasLabel = label !== undefined && label !== null
  const labelId = hasLabel ? `${progressId}-label` : undefined
  const safeMax = Number.isFinite(max) && max > 0 ? max : 100
  const safeValue =
    value === null || value === undefined
      ? undefined
      : Math.min(Math.max(value, 0), safeMax)
  const renderedValue =
    safeValue === undefined
      ? undefined
      : (formatValue?.(safeValue, safeMax) ??
        `${Math.round((safeValue / safeMax) * 100)}%`)

  return (
    <div
      className={cn(
        'ui-progress',
        tone !== 'primary' && `ui-progress--${tone}`,
        containerClassName,
      )}
    >
      {(hasLabel || showValue) && (
        <div className="ui-progress__meta">
          {hasLabel && (
            <span id={labelId} className="ui-progress__label">
              {label}
            </span>
          )}
          {showValue && renderedValue !== undefined && (
            <span className="ui-progress__value" aria-hidden="true">
              {renderedValue}
            </span>
          )}
        </div>
      )}
      <progress
        {...props}
        id={progressId}
        className={cn('ui-progress__track', className)}
        max={safeMax}
        value={safeValue}
        aria-label={!hasLabel ? (ariaLabel ?? 'Выполнение') : ariaLabel}
        aria-labelledby={hasLabel ? labelId : ariaLabelledBy}
      />
    </div>
  )
}
