import type { ComponentPropsWithRef } from 'react'

import { cn } from '../../lib/utils'

export type BadgeTone =
  'neutral' | 'positive' | 'system' | 'warning' | 'danger' | 'outline'

export interface BadgeProps extends ComponentPropsWithRef<'span'> {
  dot?: boolean
  tone?: BadgeTone
}

export function Badge({
  children,
  className,
  dot = false,
  tone = 'neutral',
  ...props
}: BadgeProps) {
  return (
    <span
      className={cn(
        'ui-badge',
        tone !== 'neutral' && `ui-badge--${tone}`,
        className,
      )}
      {...props}
    >
      {dot && <span className="ui-badge__dot" aria-hidden="true" />}
      {children}
    </span>
  )
}
