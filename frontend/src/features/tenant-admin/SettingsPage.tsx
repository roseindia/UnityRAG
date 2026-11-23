import { zodResolver } from '@hookform/resolvers/zod'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Controller, useForm } from 'react-hook-form'
import { adminApi } from '@/services/api/adminApi'
import { ApiError, fieldErrors } from '@/services/api/errors'
import { settingsSchema, type SettingsForm } from '@/schemas/admin'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input, Select, Switch } from '@/components/ui/form'
import { InlineAlert, QueryState } from '@/components/feedback/states'
import { PageHeader } from '@/components/common/display'
import { n, s, useTenantKey, useWrite, type Row } from './common'

function Form({ d }: { d: Row }) {
  const [err, setErr] = useState<string | null>(null)
  const { register, handleSubmit, control, setError, formState: { errors, isDirty } } = useForm<SettingsForm>({
    resolver: zodResolver(settingsSchema),
    defaultValues: { require_mfa_for_admin: Boolean(d.require_mfa_for_admin), session_idle_minutes: n(d.session_idle_minutes) ?? 30, session_absolute_hours: n(d.session_absolute_hours) ?? 12,
      store_query_text: Boolean(d.store_query_text), conversation_retention_days: n(d.conversation_retention_days) ?? 365, default_language: s(d.default_language, 'en-GB') },
  })
  const save = useWrite((v: SettingsForm) => adminApi.putSettings({ ...v, session_idle_minutes: Number(v.session_idle_minutes), session_absolute_hours: Number(v.session_absolute_hours), conversation_retention_days: Number(v.conversation_retention_days) }),
    { invalidate: [['admin', 'settings']], success: 'Settings saved.', silentError: true })
  return (
    <form noValidate className="space-y-4" onSubmit={handleSubmit((v) => { setErr(null); save.mutate(v, { onError: (e) => { Object.entries(fieldErrors(e)).forEach(([k, m]) => { if (k in v) setError(k as keyof SettingsForm, { message: m }) }); setErr(e instanceof ApiError ? e.message : 'Something went wrong.') } }) })}>
      {err && <InlineAlert tone="danger">{err}</InlineAlert>}
      <Card><CardHeader title="Security" /><CardBody className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><Controller control={control} name="require_mfa_for_admin" render={({ field }) => <Switch label="Require MFA for administrators" checked={field.value} onChange={field.onChange} />} /></div>
        <Field label="Session idle timeout (minutes)" error={errors.session_idle_minutes?.message} hint="5 to 1,440">{(p) => <Input {...p} type="number" {...register('session_idle_minutes')} />}</Field>
        <Field label="Session absolute lifetime (hours)" error={errors.session_absolute_hours?.message} hint="1 to 168">{(p) => <Input {...p} type="number" {...register('session_absolute_hours')} />}</Field>
      </CardBody></Card>
      <Card><CardHeader title="Privacy" /><CardBody className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2 space-y-1"><Controller control={control} name="store_query_text" render={({ field }) => <Switch label="Store query text" checked={field.value} onChange={field.onChange} />} />
          <p className="text-xs text-ink-muted">When on, the text of searches is stored and shown in history and analytics. When off, only hashes and counts are kept. Turning it on has a privacy impact: users may type personal data.</p></div>
        <Field label="Conversation retention (days)" error={errors.conversation_retention_days?.message}>{(p) => <Input {...p} type="number" {...register('conversation_retention_days')} />}</Field>
      </CardBody></Card>
      <Card><CardHeader title="Localisation" /><CardBody>
        <Field label="Default language" className="max-w-xs">{(p) => <Select {...p} {...register('default_language')}><option value="en-GB">English (UK)</option></Select>}</Field>
      </CardBody></Card>
      <Button type="submit" loading={save.isPending} disabled={!isDirty}>Save settings</Button>
    </form>
  )
}

export default function SettingsPage() {
  const key = useTenantKey()
  const q = useQuery({ queryKey: key('admin', 'settings'), queryFn: adminApi.settings })
  return (<><PageHeader title="Settings" description="Tenant-wide security, privacy and localisation." /><QueryState query={q}>{(d) => <Form d={d} />}</QueryState></>)
}
