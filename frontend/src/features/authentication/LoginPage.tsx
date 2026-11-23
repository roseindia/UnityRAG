import { zodResolver } from '@hookform/resolvers/zod'
import { useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { env } from '@/config/env'
import { useAuth } from '@/contexts/AuthContext'
import { loginSchema, type LoginForm } from '@/schemas/auth'
import { ApiError } from '@/services/api/errors'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/form'
import { InlineAlert } from '@/components/feedback/states'
import { homeFor, safeReturnTo } from '@/utils/returnTo'
import { Link } from 'react-router-dom'

export default function LoginPage() {
  const { login, status, profile, notice, needsTenantChoice } = useAuth()
  const nav = useNavigate()
  const [params] = useSearchParams()
  const errorRef = useRef<HTMLDivElement>(null)
  const [mfa, setMfa] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showLocal, setShowLocal] = useState(env.authModes.includes('local') && !env.authModes.includes('oidc'))
  const { register, handleSubmit, formState: { errors, isSubmitting }, setValue, setFocus } = useForm<LoginForm>({ resolver: zodResolver(loginSchema), defaultValues: { email: '', password: '', mfa_code: '' } })

  // Move focus to the error summary once, when an error appears (not on every render).
  useEffect(() => { if (error) errorRef.current?.focus() }, [error])

  const returnTo = params.get('returnTo')
  if (status === 'authenticated') {
    if (needsTenantChoice) return <Navigate to="/select-tenant" replace />
    return <Navigate to={returnTo ? safeReturnTo(returnTo) : homeFor(profile?.console)} replace />
  }

  const onSubmit = handleSubmit(async (v) => {
    setError(null)
    try {
      await login({ email: v.email, password: v.password, ...(mfa && v.mfa_code ? { mfa_code: v.mfa_code } : {}) })
      nav(returnTo ? safeReturnTo(returnTo) : '/', { replace: true })
    } catch (e) {
      if (e instanceof ApiError && e.code === 'mfa_required') { setMfa(true); setError(e.message); setTimeout(() => setFocus('mfa_code'), 0); return }
      if (e instanceof ApiError && e.code === 'invalid_mfa') setValue('mfa_code', '')
      if (e instanceof ApiError && e.code === 'password_login_disabled') setShowLocal(false)
      setError(e instanceof ApiError ? e.message : 'Something went wrong. Please try again.')
    }
  })

  const oidc = env.authModes.includes('oidc')
  const local = env.authModes.includes('local')

  return (
    <div className="grid min-h-screen place-items-center bg-canvas px-4">
      <main className="w-full max-w-md rounded-card border border-line bg-surface p-6 shadow-raised">
        <div className="mb-5 flex items-center gap-3">
          <img src="/logo/logo.svg" alt="" className="h-9 w-9" />
          <div>
            <h1 className="text-xl">{env.appName}</h1>
            <p className="text-xs text-ink-muted">Approved knowledge for insurance professionals.</p>
          </div>
        </div>
        {notice && <InlineAlert tone="info" className="mb-4">{notice}</InlineAlert>}
        {oidc && (
          <Button className="w-full" onClick={() => { if (env.oidcStartUrl) window.location.assign(env.oidcStartUrl); else setError('Single sign-on is not configured for this environment.') }}>
            {env.oidcDisplayName}
          </Button>
        )}
        {oidc && local && !showLocal && (
          <Button variant="link" className="mt-3" onClick={() => setShowLocal(true)}>Use email and password instead</Button>
        )}
        {local && showLocal && (
          <form onSubmit={onSubmit} noValidate className="mt-4 space-y-3" aria-label="Sign in">
            {error && <div tabIndex={-1} ref={errorRef}><InlineAlert tone={mfa ? 'info' : 'danger'}>{error}</InlineAlert></div>}
            <Field label="Email" error={errors.email?.message} required>
              {(p) => <Input {...p} type="email" autoComplete="username" {...register('email')} />}
            </Field>
            <Field label="Password" error={errors.password?.message} required>
              {(p) => <Input {...p} type="password" autoComplete="current-password" {...register('password')} />}
            </Field>
            {mfa && (
              <Field label="6-digit code" error={errors.mfa_code?.message} hint="From your authenticator app." required>
                {(p) => <Input {...p} inputMode="numeric" maxLength={6} autoComplete="one-time-code" {...register('mfa_code')} />}
              </Field>
            )}
            <Button type="submit" className="w-full" loading={isSubmitting}>Sign in</Button>
          </form>
        )}
        {!oidc && !local && <InlineAlert tone="warning">No sign-in method is configured. Contact your administrator.</InlineAlert>}
        {error && !(local && showLocal) && <InlineAlert tone="danger" className="mt-3">{error}</InlineAlert>}
        <footer className="mt-6 space-y-1 border-t border-line pt-3 text-xs text-ink-muted">
          <p>Answers are AI-generated from approved documents. Do not enter customer personal data.</p>
          <p className="flex gap-3">
            <Link className="text-primary underline" to="/reset-password">Reset password</Link>
            {env.supportUrl && <a className="text-primary underline" href={env.supportUrl} target="_blank" rel="noopener noreferrer">Help</a>}
          </p>
        </footer>
      </main>
    </div>
  )
}
