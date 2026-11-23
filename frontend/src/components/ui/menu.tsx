import * as M from '@radix-ui/react-dropdown-menu'
import type { ReactNode } from 'react'
import { cn } from '@/utils/cn'

export interface MenuItem { label: string; onSelect: () => void; icon?: ReactNode; danger?: boolean; disabled?: boolean; hidden?: boolean }

export function Menu({ trigger, items, label, align = 'end' }: { trigger: ReactNode; items: MenuItem[]; label: string; align?: 'start' | 'end' }) {
  const shown = items.filter((i) => !i.hidden)
  if (!shown.length) return null
  return (
    <M.Root>
      <M.Trigger asChild aria-label={label}>{trigger}</M.Trigger>
      <M.Portal>
        <M.Content align={align} sideOffset={4} className="z-50 min-w-[180px] rounded-card border border-line bg-surface p-1 shadow-raised">
          {shown.map((i) => (
            <M.Item key={i.label} disabled={i.disabled} onSelect={i.onSelect}
              className={cn('flex cursor-pointer items-center gap-2 rounded-control px-2 py-1.5 text-sm outline-none data-[highlighted]:bg-canvas data-[disabled]:opacity-50', i.danger && 'text-danger')}>
              {i.icon}{i.label}
            </M.Item>
          ))}
        </M.Content>
      </M.Portal>
    </M.Root>
  )
}
