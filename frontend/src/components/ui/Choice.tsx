import { useId, type ComponentPropsWithRef, type ReactNode } from 'react'

import { cn } from '../../lib/utils'

interface ChoiceProps extends Omit<
  ComponentPropsWithRef<'input'>,
  'children' | 'type'
> {
  description?: ReactNode
  label: ReactNode
  wrapperClassName?: string
}

function getDescriptionId(
  id: string,
  description: ReactNode,
): string | undefined {
  return description !== undefined && description !== null
    ? `${id}-description`
    : undefined
}

export type CheckboxProps = ChoiceProps

export function Checkbox({
  'aria-describedby': ariaDescribedBy,
  className,
  description,
  id: providedId,
  label,
  wrapperClassName,
  ...props
}: CheckboxProps) {
  const generatedId = useId()
  const inputId = providedId ?? `checkbox-${generatedId}`
  const descriptionId = getDescriptionId(inputId, description)
  const describedBy =
    [ariaDescribedBy, descriptionId].filter(Boolean).join(' ') || undefined

  return (
    <label className={cn('ui-choice', wrapperClassName)} htmlFor={inputId}>
      <input
        {...props}
        id={inputId}
        type="checkbox"
        className={cn('ui-choice__input', className)}
        aria-describedby={describedBy}
      />
      <span className="ui-checkbox__box" aria-hidden="true" />
      <span className="ui-choice__copy">
        <span className="ui-choice__label">{label}</span>
        {description !== undefined && description !== null && (
          <span id={descriptionId} className="ui-choice__description">
            {description}
          </span>
        )}
      </span>
    </label>
  )
}

export type SwitchProps = ChoiceProps

export function Switch({
  'aria-describedby': ariaDescribedBy,
  className,
  description,
  id: providedId,
  label,
  wrapperClassName,
  ...props
}: SwitchProps) {
  const generatedId = useId()
  const inputId = providedId ?? `switch-${generatedId}`
  const descriptionId = getDescriptionId(inputId, description)
  const describedBy =
    [ariaDescribedBy, descriptionId].filter(Boolean).join(' ') || undefined

  return (
    <label className={cn('ui-choice', wrapperClassName)} htmlFor={inputId}>
      <input
        {...props}
        id={inputId}
        type="checkbox"
        role="switch"
        className={cn('ui-choice__input', className)}
        aria-describedby={describedBy}
      />
      <span className="ui-switch__track" aria-hidden="true" />
      <span className="ui-choice__copy">
        <span className="ui-choice__label">{label}</span>
        {description !== undefined && description !== null && (
          <span id={descriptionId} className="ui-choice__description">
            {description}
          </span>
        )}
      </span>
    </label>
  )
}
