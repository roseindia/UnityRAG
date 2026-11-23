import * as D from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/utils/cn'

interface Props {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  description?: string
  children: ReactNode
  footer?: ReactNode
  /** "drawer" slides in from the right (previews, details); "dialog" is centred. */
  variant?: 'dialog' | 'drawer'
  size?: 'sm' | 'md' | 'lg'
  /** Dialogs of the destructive type must be closed explicitly. */
  dismissible?: boolean
}

const sizes = { sm: 'max-w-md', md: 'max-w-xl', lg: 'max-w-3xl' }

/** Accessible modal (focus trap, Esc, focus return) built on Radix Dialog. */
export function Modal({ open, onOpenChange, title, description, children, footer, variant = 'dialog', size = 'md', dismissible = true }: Props) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-nav/50" />
        <D.Content
          onInteractOutside={dismissible ? undefined : (e) => e.preventDefault()}
          aria-describedby={description ? undefined : undefined}
          className={cn(
            'fixed z-50 flex max-h-[90vh] flex-col bg-surface shadow-overlay focus:outline-none',
            variant === 'dialog'
              ? cn('left-1/2 top-1/2 w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 rounded-card', sizes[size])
              : 'right-0 top-0 h-full max-h-none w-full max-w-xl sm:w-[480px]',
          )}
        >
          <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
            <div>
              <D.Title className="text-base font-semibold">{title}</D.Title>
              {description ? <D.Description className="mt-0.5 text-xs text-ink-muted">{description}</D.Description> : <D.Description className="sr-only">{title}</D.Description>}
            </div>
            <D.Close className="rounded-control p-1 hover:bg-canvas" aria-label="Close"><X className="h-4 w-4" aria-hidden /></D.Close>
          </div>
          <div className="flex-1 overflow-y-auto p-4">{children}</div>
          {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
