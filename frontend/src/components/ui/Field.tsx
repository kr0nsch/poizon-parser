import { useId, type ComponentPropsWithRef, type ReactNode } from 'react'

import { cn } from '../../lib/utils'

export type InputProps = ComponentPropsWithRef<'input'>

export function Input({ className, ...props }: InputProps) {
  return <input className={cn('ui-input', className)} {...props} />
}

export type FieldLabelProps = ComponentPropsWithRef<'label'>

export function FieldLabel({ className, ...props }: FieldLabelProps) {
  return <label className={cn('ui-field__label', className)} {...props} />
}

export type FieldHintProps = ComponentPropsWithRef<'p'>

export function FieldHint({ className, ...props }: FieldHintProps) {
  return <p className={cn('ui-field__hint', className)} {...props} />
}

export type FieldErrorProps = ComponentPropsWithRef<'p'>

export function FieldError({ className, ...props }: FieldErrorProps) {
  return <p className={cn('ui-field__error', className)} {...props} />
}

export interface FieldProps extends InputProps {
  containerClassName?: string
  error?: ReactNode
  hint?: ReactNode
  label: ReactNode
  optionalLabel?: ReactNode
}

export function Field({
  'aria-describedby': ariaDescribedBy,
  'aria-invalid': ariaInvalid,
  className,
  containerClassName,
  error,
  hint,
  id: providedId,
  label,
  optionalLabel,
  required,
  ...props
}: FieldProps) {
  const generatedId = useId()
  const inputId = providedId ?? `field-${generatedId}`
  const hasHint = hint !== undefined && hint !== null
  const hasError = error !== undefined && error !== null
  const hintId = hasHint ? `${inputId}-hint` : undefined
  const errorId = hasError ? `${inputId}-error` : undefined
  const describedBy =
    [ariaDescribedBy, hintId, errorId].filter(Boolean).join(' ') || undefined

  return (
    <div className={cn('ui-field', containerClassName)}>
      <div className="ui-field__label-row">
        <FieldLabel htmlFor={inputId}>
          {label}
          {required && (
            <span className="ui-field__required" aria-hidden="true">
              *
            </span>
          )}
        </FieldLabel>
        {optionalLabel !== undefined && optionalLabel !== null && (
          <span className="ui-field__optional">{optionalLabel}</span>
        )}
      </div>
      <Input
        {...props}
        id={inputId}
        className={className}
        required={required}
        aria-describedby={describedBy}
        aria-invalid={hasError ? true : ariaInvalid}
      />
      {hasHint && <FieldHint id={hintId}>{hint}</FieldHint>}
      {hasError && (
        <FieldError id={errorId} role="alert">
          {error}
        </FieldError>
      )}
    </div>
  )
}
