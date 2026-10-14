import type { LucideIcon } from 'lucide-react'
import type { Ref } from 'react'

interface EmptyStateProps {
  description: string
  icon: LucideIcon
  /** Для переноса фокуса сюда, когда исчез последний элемент списка. */
  ref?: Ref<HTMLDivElement>
  title: string
}

export function EmptyState({
  description,
  icon: Icon,
  ref,
  title,
}: EmptyStateProps) {
  return (
    <div className="empty-state" ref={ref} tabIndex={ref ? -1 : undefined}>
      <div>
        <span className="empty-state__icon" aria-hidden="true">
          <Icon size={24} />
        </span>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </div>
  )
}
