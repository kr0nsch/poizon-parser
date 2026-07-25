import type { LucideIcon } from 'lucide-react'

interface EmptyStateProps {
  description: string
  icon: LucideIcon
  title: string
}

export function EmptyState({
  description,
  icon: Icon,
  title,
}: EmptyStateProps) {
  return (
    <div className="empty-state">
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
