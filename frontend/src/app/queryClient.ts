import { QueryClient } from '@tanstack/react-query'
import { ApiError } from '@/services/api/errors'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (count, error) => {
        // 4xx are deterministic outcomes (403/404 are normal): never retry them.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
        return count < 1
      },
    },
  },
})
