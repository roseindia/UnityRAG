import * as T from '@radix-ui/react-tabs'
import type { ReactNode } from 'react'
import { cn } from '@/utils/cn'

export interface TabDef { value: string; label: string; content: ReactNode; hidden?: boolean }

/** Controlled tabs; value usually lives in the URL (?tab=) so it can be shared. */
export function Tabs({ tabs, value, onValueChange }: { tabs: TabDef[]; value: string; onValueChange: (v: string) => void }) {
  const visible = tabs.filter((t) => !t.hidden)
  return (
    <T.Root value={value} onValueChange={onValueChange}>
      <T.List className="mb-4 flex gap-1 overflow-x-auto border-b border-line" aria-label="Sections">
        {visible.map((t) => (
          <T.Trigger key={t.value} value={t.value}
            className={cn('whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm font-medium text-ink-muted hover:text-ink data-[state=active]:border-primary data-[state=active]:text-primary')}>
            {t.label}
          </T.Trigger>
        ))}
      </T.List>
      {visible.map((t) => <T.Content key={t.value} value={t.value} className="focus:outline-none">{t.content}</T.Content>)}
    </T.Root>
  )
}
