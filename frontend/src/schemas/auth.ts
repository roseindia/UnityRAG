import { z } from 'zod'

export const loginSchema = z.object({
  email: z.string().trim().min(1, 'Enter your email address.').email('Enter a valid email address.'),
  password: z.string().min(1, 'Enter your password.'),
  mfa_code: z.string().regex(/^\d{6}$/, 'Enter the 6-digit code.').optional().or(z.literal('')),
})
export type LoginForm = z.infer<typeof loginSchema>

/** Live strength checklist; the server policy is authoritative and its messages are shown verbatim. */
export const passwordRules = [
  { id: 'len', label: 'At least 12 characters', test: (s: string) => s.length >= 12 },
  { id: 'upper', label: 'An upper-case letter', test: (s: string) => /[A-Z]/.test(s) },
  { id: 'lower', label: 'A lower-case letter', test: (s: string) => /[a-z]/.test(s) },
  { id: 'digit', label: 'A digit', test: (s: string) => /\d/.test(s) },
  { id: 'symbol', label: 'A symbol', test: (s: string) => /[^A-Za-z0-9]/.test(s) },
] as const

export const changePasswordSchema = z.object({
  current_password: z.string().min(1, 'Enter your current password.'),
  new_password: z.string().min(1, 'Enter a new password.'),
  confirm: z.string(),
}).refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'The passwords do not match.' })
export type ChangePasswordForm = z.infer<typeof changePasswordSchema>

export const resetPasswordSchema = z.object({
  token: z.string().trim().min(1, 'Enter the reset token you were given.'),
  new_password: z.string().min(1, 'Enter a new password.'),
  confirm: z.string(),
}).refine((v) => v.new_password === v.confirm, { path: ['confirm'], message: 'The passwords do not match.' })
export type ResetPasswordForm = z.infer<typeof resetPasswordSchema>
