import type { ComponentPropsWithRef } from 'react'

import { cn } from '../../lib/utils'

export interface SelectProps extends ComponentPropsWithRef<'select'> {
  wrapperClassName?: string
}

export function Select({
  children,
  className,
  wrapperClassName,
  ...props
}: SelectProps) {
  return (
    <span className={cn('ui-select-wrap', wrapperClassName)}>
      <select className={cn('ui-select', className)} {...props}>
        {children}
      </select>
      <span className="ui-select__chevron" aria-hidden="true" />
    </span>
  )
}
