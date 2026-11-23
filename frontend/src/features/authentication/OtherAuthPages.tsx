import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import { useAuth } from '@/contexts/AuthContext'
import { authApi } from '@/services/api/authApi'
import { ApiError, fieldErrors } from '@/services/api/errors'
import { passwordRules, resetPasswordSchema, type ResetPasswordForm } from '@/schemas/auth'
import { Button } from '@/components/ui/button'
import { Card, CardBody, Badge } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/form'
import { InlineAlert } from '@/components/feedback/states'
import { homeFor, safeReturnTo } from '@/utils/returnTo'

/** Tenant picker: a card per membership; suspended tenants and inactive memberships are disabled with an explanation. */
export function TenantPickerPage() {
  const { memberships, profile, selectTenant, confirmTenant, status } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (status !== 'authenticated') return <Navigate to="/login" replace />
  const sorted = [...memberships].sort((a, b) => Number(b.is_default) - Number(a.is_default))
  const from = (loc.state as { from?: string } | null)?.from

  const choose = async (id: string) => {
    setBusy(id); setError(null)
    try {
      if (id === profile?.tenant_id) confirmTenant()
      else await selectTenant(id)
      confirmTenant()
      nav(from ? safeReturnTo(from) : homeFor(profile?.console), { replace: true })
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not select this organisation.'); setBusy(null)
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-xl">Choose an organisation</h1>
      <p className="mb-4 text-ink-muted">You belong to more than one organisation. You can switch later from the top bar.</p>
      {error && <InlineAlert tone="danger" className="mb-3">{error}</InlineAlert>}
      <ul className="grid gap-3 sm:grid-cols-2">
        {sorted.map((m) => {
          const usable = m.membership_status === 'active' && m.tenant_status === 'active'
          return (
            <li key={m.tenant_id}>
              <Card className={usable ? '' : 'opacity-70'}>
                <CardBody className="space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <div><p className="font-medium">{m.tenant_name}</p><p className="font-mono text-xs text-ink-muted">{m.tenant_code}</p></div>
                    <Badge tone={m.tenant_status === 'active' ? 'success' : 'warning'}>{m.tenant_status}</Badge>
                  </div>
                  {m.is_default && <Badge tone="info">Default</Badge>}
                  {!usable && <p className="text-xs text-ink-muted">{m.tenant_status !== 'active' ? 'This organisation is not active.' : 'Your access to this organisation is not active.'}</p>}
                  <Button className="w-full" disabled={!usable || (busy !== null && busy !== m.tenant_id)} loading={busy === m.tenant_id} onClick={() => void choose(m.tenant_id)}>
                    {m.tenant_id === profile?.tenant_id ? 'Continue' : 'Select'}
                  </Button>
                </CardBody>
              </Card>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** The return leg of SSO. A deployment BFF/IdP broker delivers the IdP token in the URL fragment; it is exchanged and removed from history. */
export function LoginCallbackPage() {
  const { loginWithOidc } = useAuth()
  const nav = useNavigate()
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const frag = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    const token = frag.get('id_token')
    window.history.replaceState(null, '', window.location.pathname)
    if (!token) { setError('Sign-in did not complete. Please try again.'); return }
    loginWithOidc(token).then(() => nav('/', { replace: true })).catch((e) => setError(e instanceof ApiError ? e.message : 'Sign-in failed.'))
  }, [loginWithOidc, nav])
  return (
    <div className="mx-auto mt-24 max-w-sm px-4 text-center" role="status">
      {error ? (<><InlineAlert tone="danger">{error}</InlineAlert><Button asChild className="mt-4"><Link to="/login">Back to sign in</Link></Button></>) : <p>Signing you in…</p>}
    </div>
  )
}

export function PasswordChecklist({ value }: { value: string }) {
  return (
    <ul className="mt-1 space-y-0.5 text-xs" aria-label="Password requirements">
      {passwordRules.map((r) => <li key={r.id} className={r.test(value) ? 'text-success' : 'text-ink-muted'}>{r.test(value) ? '✓' : '○'} {r.label}</li>)}
    </ul>
  )
}

/** Complete a reset with the single-use token an administrator handed over (there is no e-mail delivery yet). */
export function ResetPasswordPage() {
  const [params] = useSearchParams()
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { register, handleSubmit, watch, setError: setFieldError, formState: { errors, isSubmitting } } = useForm<ResetPasswordForm>({
    resolver: zodResolver(resetPasswordSchema), defaultValues: { token: params.get('token') ?? '', new_password: '', confirm: '' },
  })
  const pwd = watch('new_password')
  const onSubmit = handleSubmit(async (v) => {
    setError(null)
    try { await authApi.resetPassword(v.token, v.new_password); setDone(true); toast.success('Password updated. You can sign in now.') }
    catch (e) {
      const fe = fieldErrors(e)
      if (fe.new_password) setFieldError('new_password', { message: fe.new_password })
      setError(e instanceof ApiError ? (e.serverMessage && e.code === 'validation_failed' ? e.serverMessage : e.message) : 'Something went wrong.')
    }
  })
  return (
    <div className="grid min-h-screen place-items-center bg-canvas px-4">
      <main className="w-full max-w-md rounded-card border border-line bg-surface p-6 shadow-raised">
        <h1 className="mb-1 text-xl">Reset your password</h1>
        <p className="mb-4 text-ink-muted">Enter the reset token your administrator gave you.</p>
        {done ? (<><InlineAlert tone="success">Your password has been changed.</InlineAlert><Button asChild className="mt-4 w-full"><Link to="/login">Go to sign in</Link></Button></>) : (
          <form onSubmit={onSubmit} noValidate className="space-y-3">
            {error && <InlineAlert tone="danger">{error}</InlineAlert>}
            <Field label="Reset token" error={errors.token?.message} required>{(p) => <Input {...p} autoComplete="off" {...register('token')} />}</Field>
            <Field label="New password" error={errors.new_password?.message} required>{(p) => <Input {...p} type="password" autoComplete="new-password" {...register('new_password')} />}</Field>
            <PasswordChecklist value={pwd} />
            <Field label="Confirm new password" error={errors.confirm?.message} required>{(p) => <Input {...p} type="password" autoComplete="new-password" {...register('confirm')} />}</Field>
            <Button type="submit" className="w-full" loading={isSubmitting}>Change password</Button>
            <p className="text-center text-xs"><Link className="text-primary underline" to="/login">Back to sign in</Link></p>
          </form>
        )}
      </main>
    </div>
  )
}
