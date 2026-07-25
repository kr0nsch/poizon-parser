import type { ComponentPropsWithRef, ReactNode } from 'react'

import { cn } from '../../lib/utils'

export type ButtonVariant =
  'primary' | 'secondary' | 'quiet' | 'system' | 'danger'

export type ButtonSize = 'sm' | 'md' | 'lg' | 'icon'

export interface ButtonProps extends ComponentPropsWithRef<'button'> {
  loading?: boolean
  loadingLabel?: ReactNode
  size?: ButtonSize
  variant?: ButtonVariant
}

export function Button({
  children,
  className,
  disabled,
  loading = false,
  loadingLabel,
  size = 'md',
  type = 'button',
  variant = 'primary',
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        'ui-button',
        `ui-button--${variant}`,
        size !== 'md' && `ui-button--${size}`,
        className,
      )}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <span className="ui-button__spinner" aria-hidden="true" />}
      {loading && loadingLabel !== undefined ? loadingLabel : children}
    </button>
  )
}
