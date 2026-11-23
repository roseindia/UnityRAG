import { QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { queryClient } from '@/app/queryClient'
import { AuthProvider } from '@/contexts/AuthContext'
import { BreakGlassProvider } from '@/contexts/BreakGlassContext'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ErrorBoundary } from '@/components/feedback/ErrorBoundary'

export function Providers({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary name="root">
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BreakGlassProvider>
            <TooltipProvider>{children}</TooltipProvider>
          </BreakGlassProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
