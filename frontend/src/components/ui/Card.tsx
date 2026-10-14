import type { ComponentPropsWithRef } from 'react'

import { cn } from '../../lib/utils'

export type SurfaceTone =
  'default' | 'subtle' | 'raised' | 'system' | 'warning' | 'danger'

export interface CardProps extends ComponentPropsWithRef<'div'> {
  tone?: SurfaceTone
}

export function Card({ className, tone = 'default', ...props }: CardProps) {
  return (
    <div
      className={cn(
        'ui-card',
        tone !== 'default' && `ui-card--${tone}`,
        className,
      )}
      {...props}
    />
  )
}

export interface PanelProps extends ComponentPropsWithRef<'section'> {
  tone?: SurfaceTone
}

export function Panel({ className, tone = 'default', ...props }: PanelProps) {
  return (
    <section
      className={cn(
        'ui-panel',
        tone !== 'default' && `ui-panel--${tone}`,
        className,
      )}
      {...props}
    />
  )
}

export type CardContentProps = ComponentPropsWithRef<'div'>

export function CardContent({ className, ...props }: CardContentProps) {
  return <div className={cn('ui-card__content', className)} {...props} />
}
