// Error envelope: {"error": {"code","message","correlation_id","details"}} (Design Document 6.3, Appendix B)
export interface ApiErrorDetail { field?: string; loc?: (string | number)[]; message?: string; msg?: string; [k: string]: unknown }

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly correlationId?: string
  readonly details: ApiErrorDetail[]
  readonly retryAfter?: number
  readonly serverMessage?: string

  constructor(o: { status: number; code: string; correlationId?: string; details?: ApiErrorDetail[]; retryAfter?: number; serverMessage?: string }) {
    super(userMessage(o.code))
    this.name = 'ApiError'
    this.status = o.status
    this.code = o.code
    this.correlationId = o.correlationId
    this.details = o.details ?? []
    this.retryAfter = o.retryAfter
    this.serverMessage = o.serverMessage
  }
}

const CATALOGUE: Record<string, string> = {
  invalid_credentials: 'The email or password is incorrect.',
  mfa_required: 'Enter the 6-digit code from your authenticator app.',
  invalid_mfa: "That code didn't work. Check the time on your device and try again.",
  account_locked: 'Your account is temporarily locked. Try again later or contact your administrator.',
  account_inactive: 'Your access to this organisation is not active.',
  user_inactive: 'Your access to this organisation is not active.',
  membership_inactive: 'Your access to this organisation is not active.',
  not_provisioned: "Your account hasn't been set up for this platform. Contact your administrator.",
  sso_not_configured: "Your account hasn't been set up for this platform. Contact your administrator.",
  password_login_disabled: 'Please sign in with your organisation account.',
  token_reuse: 'Your session ended for security reasons. Please sign in again.',
  invalid_refresh_token: 'Your session ended for security reasons. Please sign in again.',
  step_up_required: "Confirm it's you to continue.",
  permission_denied: "You don't have permission to do this.",
  tenant_unavailable: "Your organisation's access is currently suspended.",
  tenant_not_authorized: 'This organisation is not available to your account.',
  tenant_context_required: 'This organisation is not available to your account.',
  setting_not_overridable: "This setting is managed by the platform and can't be changed here.",
  system_role_protected: "System roles can't be changed. Create a custom role instead.",
  break_glass_inactive: 'Support access has expired or was closed.',
  not_found: 'Not found, or no longer available to you.',
  conflict: 'This item already exists.',
  duplicate_document: 'This item already exists.',
  duplicate_version: 'This item already exists.',
  legal_hold: "This item is under legal hold and can't be deleted.",
  payload_too_large: 'The file is too large.',
  validation_failed: 'Please correct the highlighted fields.',
  unsupported_file_type: "This file type isn't supported, or its content doesn't match its extension.",
  rate_limited: 'Too many requests. Please wait a moment.',
  quota_exceeded: 'Your organisation has reached its limit for this. Contact your administrator.',
  internal_error: 'Something went wrong on our side. Please try again.',
  service_unavailable: 'Something went wrong on our side. Please try again.',
  network_error: 'We could not reach the server. Check your connection and try again.',
  aborted: 'The request was cancelled.',
}
export const GENERIC_ERROR = 'Something went wrong. Please try again.'

export function userMessage(code: string): string {
  return CATALOGUE[code] ?? GENERIC_ERROR
}

/** Validation details → { 'body.chunk_size': 'message', 'chunk_size': 'message' }. */
export function fieldErrors(e: unknown): Record<string, string> {
  const out: Record<string, string> = {}
  if (!(e instanceof ApiError)) return out
  for (const d of e.details) {
    const path = d.field ?? (Array.isArray(d.loc) ? d.loc.join('.') : undefined)
    const msg = d.message ?? d.msg
    if (!path || !msg) continue
    out[path] = msg
    const last = path.split('.').pop()
    if (last) out[last] = msg
  }
  return out
}

export function errorFromResponse(status: number, data: unknown, headers: Record<string, unknown> = {}): ApiError {
  const body = (data as { error?: Record<string, unknown> } | undefined)?.error
  const code = typeof body?.code === 'string' ? body.code : status === 404 ? 'not_found' : status >= 500 ? 'internal_error' : 'error'
  const retry = Number(headers['retry-after'])
  return new ApiError({
    status, code,
    correlationId: (typeof body?.correlation_id === 'string' ? body.correlation_id : undefined) ?? (headers['x-correlation-id'] as string | undefined),
    details: Array.isArray(body?.details) ? (body?.details as ApiErrorDetail[]) : [],
    retryAfter: Number.isFinite(retry) ? retry : undefined,
    serverMessage: typeof body?.message === 'string' ? body.message : undefined,
  })
}
