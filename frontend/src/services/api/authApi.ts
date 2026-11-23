import { get, post } from './apiClient'
import type { LoginRequest, Membership, Message, Profile, TokenResponse, Row } from '@/types/api'

export const authApi = {
  login: (b: LoginRequest) => post<TokenResponse>('/auth/login', b),
  oidcExchange: (id_token: string, tenant_id?: string) => post<TokenResponse>('/auth/oidc/exchange', { id_token, tenant_id }),
  refresh: (refresh_token: string) => post<TokenResponse>('/auth/refresh', { refresh_token }),
  logout: () => post<Message>('/auth/logout'),
  me: (signal?: AbortSignal) => get<Profile>('/auth/me', undefined, { signal }),
  tenants: () => get<Membership[]>('/auth/tenants'),
  selectTenant: (tenant_id: string) => post<TokenResponse>('/auth/select-tenant', { tenant_id }),
  sessions: () => get<Row[]>('/auth/sessions'),
  mfaEnroll: () => post<{ secret?: string; otpauth_uri?: string; uri?: string }>('/auth/mfa/enroll'),
  mfaVerify: (code: string) => post<Message>('/auth/mfa/verify', { code }),
  changePassword: (current_password: string, new_password: string) => post<Message>('/auth/password/change', { current_password, new_password }),
  resetPassword: (token: string, new_password: string) => post<Message>('/auth/password/reset', { token, new_password }),
}
