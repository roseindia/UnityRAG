import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery } from '@tanstack/react-query'
import { QRCodeSVG } from 'qrcode.react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { useAuth } from '@/contexts/AuthContext'
import { authApi } from '@/services/api/authApi'
import { ApiError, fieldErrors } from '@/services/api/errors'
import { changePasswordSchema, type ChangePasswordForm } from '@/schemas/auth'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, Badge } from '@/components/ui/card'
import { Field, Input, Switch } from '@/components/ui/form'
import { Tabs } from '@/components/ui/tabs'
import { InlineAlert, QueryState } from '@/components/feedback/states'
import { KeyValueList, PageHeader } from '@/components/common/display'
import { CopyButton } from '@/components/common/CopyButton'
import { formatDateTime, humanize } from '@/utils/format'
import { PasswordChecklist } from './OtherAuthPages'
import type { Row } from '@/types/api'

function Identity() {
  const { profile, memberships } = useAuth()
  if (!profile) return null
  const tenant = memberships.find((m) => m.tenant_id === profile.tenant_id)
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card><CardHeader title="Identity" /><CardBody>
        <KeyValueList items={[
          { label: 'Name', value: profile.display_name }, { label: 'Email', value: profile.email },
          { label: 'User type', value: humanize(profile.user_type) }, { label: 'Organisation', value: tenant?.tenant_name ?? '–' },
        ]} /></CardBody></Card>
      <Card><CardHeader title="Your access" description="Read-only. Entitlements are managed by your administrator." /><CardBody>
        <KeyValueList items={[
          { label: 'Roles', value: <span className="flex flex-wrap gap-1">{profile.roles.length ? profile.roles.map((r) => <Badge key={r} tone="info">{humanize(r)}</Badge>) : '–'}</span> },
          { label: 'Lines of business', value: profile.lines_of_business.join(', ') || 'All permitted' },
          { label: 'Jurisdictions', value: profile.jurisdictions.join(', ') || 'All permitted' },
          { label: 'Clearance level', value: String(profile.clearance_rank) },
        ]} /></CardBody></Card>
      <Card className="lg:col-span-2"><CardHeader title="Preferences" description="Stored in this browser only until a preferences service exists." /><CardBody>
        <ShortcutToggle />
      </CardBody></Card>
    </div>
  )
}

function ShortcutToggle() {
  const [on, setOn] = useState(() => { try { return localStorage.getItem('erag.shortcuts') !== 'off' } catch { return true } })
  return <Switch label="Keyboard shortcuts" checked={on} onChange={(v) => { setOn(v); try { localStorage.setItem('erag.shortcuts', v ? 'on' : 'off') } catch { /* ignore */ } toast.success('Reload the page to apply the change.') }} />
}

function Mfa() {
  const { profile, reloadProfile } = useAuth()
  const [enrol, setEnrol] = useState<{ secret?: string; uri?: string } | null>(null)
  const [code, setCode] = useState('')
  const start = useMutation({ mutationFn: authApi.mfaEnroll, onSuccess: (d) => setEnrol({ secret: d.secret, uri: d.otpauth_uri ?? d.uri }), onError: (e) => toast.error((e as ApiError).message) })
  const verify = useMutation({
    mutationFn: () => authApi.mfaVerify(code),
    onSuccess: async () => { toast.success('Authenticator confirmed.'); setEnrol(null); setCode(''); await reloadProfile() },
    onError: (e) => toast.error((e as ApiError).message),
  })
  return (
    <Card><CardHeader title="Two-step verification" actions={<Badge tone={profile?.mfa_verified ? 'success' : 'warning'}>{profile?.mfa_verified ? 'Verified this session' : 'Not verified this session'}</Badge>} />
      <CardBody className="space-y-3">
        {!enrol ? <Button variant="secondary" loading={start.isPending} onClick={() => start.mutate()}>Set up authenticator</Button> : (
          <div className="space-y-3">
            <InlineAlert tone="warning">The secret is shown once. Scan the code or copy the secret into your authenticator app now.</InlineAlert>
            {enrol.uri && <div className="w-fit rounded-card border border-line bg-white p-3"><QRCodeSVG value={enrol.uri} size={160} title="Authenticator QR code" /></div>}
            {enrol.secret && <p className="flex items-center gap-1 font-mono text-sm">{enrol.secret}<CopyButton text={enrol.secret} label="Copy secret" /></p>}
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); verify.mutate() }}>
              <Field label="6-digit code" className="w-40">{(p) => <Input {...p} inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />}</Field>
              <Button type="submit" loading={verify.isPending} disabled={code.length !== 6}>Verify</Button>
            </form>
          </div>
        )}
      </CardBody></Card>
  )
}

function Sessions() {
  const q = useQuery({ queryKey: ['me', 'sessions'], queryFn: authApi.sessions })
  return (
    <Card><CardHeader title="Your sessions" description="Devices currently signed in to your account." />
      <QueryState query={q} isEmpty={(d) => d.length === 0}>
        {(rows: Row[]) => (
          <div className="table-wrap border-0"><table className="tbl"><caption className="sr-only">Sessions</caption>
            <thead><tr><th scope="col">Device</th><th scope="col">IP address</th><th scope="col">Created</th><th scope="col">Last seen</th></tr></thead>
            <tbody>{rows.map((r, i) => <tr key={String(r.session_id ?? i)}>
              <td>{String(r.user_agent ?? r.device ?? '–')}</td><td className="font-mono text-xs">{String(r.ip_address ?? r.ip ?? '–')}</td>
              <td>{formatDateTime(r.created_at as string)}</td><td>{formatDateTime((r.last_seen_at ?? r.last_used_at) as string)}</td></tr>)}</tbody></table></div>
        )}
      </QueryState></Card>
  )
}

function ChangePassword() {
  const { register, handleSubmit, watch, reset, setError, formState: { errors, isSubmitting } } = useForm<ChangePasswordForm>({ resolver: zodResolver(changePasswordSchema), defaultValues: { current_password: '', new_password: '', confirm: '' } })
  const [msg, setMsg] = useState<string | null>(null)
  const onSubmit = handleSubmit(async (v) => {
    setMsg(null)
    try { await authApi.changePassword(v.current_password, v.new_password); toast.success('Password changed.'); reset() }
    catch (e) {
      const fe = fieldErrors(e)
      if (fe.new_password) setError('new_password', { message: fe.new_password })
      if (fe.current_password) setError('current_password', { message: fe.current_password })
      setMsg(e instanceof ApiError ? (e.serverMessage ?? e.message) : 'Something went wrong.')
    }
  })
  return (
    <Card><CardHeader title="Change password" description="Local accounts only. Accounts that sign in through your organisation use its own password." />
      <CardBody>
        <form onSubmit={onSubmit} noValidate className="max-w-md space-y-3">
          {msg && <InlineAlert tone="danger">{msg}</InlineAlert>}
          <Field label="Current password" error={errors.current_password?.message} required>{(p) => <Input {...p} type="password" autoComplete="current-password" {...register('current_password')} />}</Field>
          <Field label="New password" error={errors.new_password?.message} required>{(p) => <Input {...p} type="password" autoComplete="new-password" {...register('new_password')} />}</Field>
          <PasswordChecklist value={watch('new_password')} />
          <Field label="Confirm new password" error={errors.confirm?.message} required>{(p) => <Input {...p} type="password" autoComplete="new-password" {...register('confirm')} />}</Field>
          <Button type="submit" loading={isSubmitting}>Change password</Button>
        </form>
      </CardBody></Card>
  )
}

export default function ProfilePage() {
  const nav = useNavigate()
  const { pathname } = useLocation()
  const tab = pathname.endsWith('/security') ? 'security' : 'profile'
  return (
    <>
      <PageHeader title="Profile" description="Your identity, access and security settings." />
      <Tabs value={tab} onValueChange={(v) => nav(v === 'security' ? '/profile/security' : '/profile')} tabs={[
        { value: 'profile', label: 'Profile', content: <Identity /> },
        { value: 'security', label: 'Security', content: <div className="space-y-4"><Mfa /><Sessions /><ChangePassword /></div> },
      ]} />
    </>
  )
}
