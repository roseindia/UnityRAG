import * as T from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

export const TooltipProvider = T.Provider

export function Tip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <T.Root delayDuration={200}>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content sideOffset={4} className="z-50 max-w-xs rounded-control bg-nav px-2 py-1 text-xs text-white shadow-raised">{text}</T.Content>
      </T.Portal>
    </T.Root>
  )
}
