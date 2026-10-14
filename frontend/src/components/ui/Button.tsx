import type { ComponentPropsWithRef, MouseEvent, ReactNode } from 'react'

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
  'aria-disabled': ariaDisabled,
  children,
  className,
  disabled,
  loading = false,
  loadingLabel,
  onClick,
  size = 'md',
  type = 'button',
  variant = 'primary',
  ...props
}: ButtonProps) {
  // Загрузка и aria-disabled не ставят нативный disabled: браузер снял бы
  // фокус с нажатой кнопки. Нажатия в этом состоянии гасим сами.
  const blocked = loading || ariaDisabled === true || ariaDisabled === 'true'

  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (blocked) {
      event.preventDefault()
      return
    }
    onClick?.(event)
  }

  return (
    <button
      className={cn(
        'ui-button',
        `ui-button--${variant}`,
        size !== 'md' && `ui-button--${size}`,
        className,
      )}
      type={type}
      disabled={disabled}
      aria-disabled={blocked || undefined}
      aria-busy={loading || undefined}
      onClick={handleClick}
      {...props}
    >
      {loading && <span className="ui-button__spinner" aria-hidden="true" />}
      {loading && loadingLabel !== undefined ? loadingLabel : children}
    </button>
  )
}
