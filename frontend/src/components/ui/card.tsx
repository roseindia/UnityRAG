import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/utils/cn'

export function Card({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-card border border-line bg-surface', className)} {...p} />
}

export function CardHeader({ title, actions, description }: { title: ReactNode; actions?: ReactNode; description?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-line px-4 py-3">
      <div>
        <h2>{title}</h2>
        {description && <p className="mt-0.5 text-xs text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

export function CardBody({ className, ...p }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-4', className)} {...p} />
}

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'primary'
const tones: Record<Tone, string> = {
  neutral: 'bg-canvas text-ink-muted border border-line',
  success: 'bg-success-bg text-success',
  warning: 'bg-warning-bg text-warning',
  danger: 'bg-danger-bg text-danger',
  info: 'bg-info-bg text-primary',
  primary: 'bg-primary text-white',
}

export function Badge({ tone = 'neutral', className, ...p }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={cn('inline-flex items-center gap-1 rounded-pill px-2 py-0.5 text-xs font-medium', tones[tone], className)} {...p} />
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-control bg-line/70', className)} aria-hidden />
}

export type { Tone }
