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

export type CardHeaderProps = ComponentPropsWithRef<'header'>

export function CardHeader({ className, ...props }: CardHeaderProps) {
  return <header className={cn('ui-card__header', className)} {...props} />
}

export type CardHeadingProps = ComponentPropsWithRef<'div'>

export function CardHeading({ className, ...props }: CardHeadingProps) {
  return <div className={cn('ui-card__heading', className)} {...props} />
}

export interface CardTitleProps extends ComponentPropsWithRef<'h2'> {
  as?: 'h2' | 'h3' | 'h4'
}

export function CardTitle({
  as: Title = 'h2',
  className,
  ...props
}: CardTitleProps) {
  return <Title className={cn('ui-card__title', className)} {...props} />
}

export type CardDescriptionProps = ComponentPropsWithRef<'p'>

export function CardDescription({ className, ...props }: CardDescriptionProps) {
  return <p className={cn('ui-card__description', className)} {...props} />
}

export type CardContentProps = ComponentPropsWithRef<'div'>

export function CardContent({ className, ...props }: CardContentProps) {
  return <div className={cn('ui-card__content', className)} {...props} />
}

export type CardFooterProps = ComponentPropsWithRef<'footer'>

export function CardFooter({ className, ...props }: CardFooterProps) {
  return <footer className={cn('ui-card__footer', className)} {...props} />
}
