const raw = import.meta.env

export const env = {
  apiBaseUrl: (raw.VITE_API_BASE_URL as string | undefined) ?? '/api/v1',
  appName: (raw.VITE_APP_NAME as string | undefined) ?? 'UnityRAG',
  mockApi: raw.VITE_ENABLE_MOCK_API === 'true' && raw.DEV === true,
  authModes: ((raw.VITE_AUTH_MODES as string | undefined) ?? 'local').split(',').map((s) => s.trim()).filter(Boolean),
  oidcStartUrl: (raw.VITE_OIDC_START_URL as string | undefined) ?? '',
  oidcDisplayName: (raw.VITE_OIDC_DISPLAY_NAME as string | undefined) ?? 'Sign in with your organisation',
  chatStreaming: (raw.VITE_CHAT_STREAMING as string | undefined) !== 'false',
  sessionIdleMinutes: Number(raw.VITE_SESSION_IDLE_MINUTES ?? 30),
  supportUrl: (raw.VITE_SUPPORT_URL as string | undefined) ?? '',
  usagePolicyUrl: (raw.VITE_USAGE_POLICY_URL as string | undefined) ?? '',
} as const
