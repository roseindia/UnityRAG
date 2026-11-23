import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { registerStepUp } from '@/services/api/apiClient'
import { authApi } from '@/services/api/authApi'
import { Modal } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/form'
import { InlineAlert } from '@/components/feedback/states'
import { ApiError } from '@/services/api/errors'

/** "Confirm it's you" dialog. Pauses the failed request, verifies a TOTP code, then lets the client replay it once. */
export function StepUpProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [code, setCode] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const resolver = useRef<((ok: boolean) => void) | null>(null)

  const finish = useCallback((ok: boolean) => {
    resolver.current?.(ok)
    resolver.current = null
    setOpen(false); setCode(''); setErr(null); setBusy(false)
    if (!ok) toast.error('Not saved. Verification was cancelled.')
  }, [])

  useEffect(() => {
    registerStepUp(() => new Promise<boolean>((resolve) => { resolver.current = resolve; setOpen(true) }))
    return () => registerStepUp(null)
  }, [])

  const verify = async () => {
    setBusy(true); setErr(null)
    try { await authApi.mfaVerify(code); finish(true) }
    catch (e) { setErr(e instanceof ApiError ? e.message : 'Verification failed.'); setBusy(false) }
  }

  return (
    <>
      {children}
      <Modal open={open} onOpenChange={(o) => { if (!o) finish(false) }} title="Confirm it's you" size="sm" dismissible={false}
        description="Your organisation requires a fresh verification for administrative changes."
        footer={<><Button variant="secondary" onClick={() => finish(false)}>Cancel</Button><Button onClick={verify} loading={busy} disabled={code.length !== 6}>Verify and continue</Button></>}>
        <form onSubmit={(e) => { e.preventDefault(); if (code.length === 6) void verify() }} className="space-y-3">
          <Field label="6-digit code" required>
            {(p) => <Input {...p} inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} />}
          </Field>
          {err && <InlineAlert tone="danger">{err}</InlineAlert>}
          <p className="text-xs text-ink-muted">No authenticator yet? <Link className="text-primary underline" to="/profile/security" onClick={() => finish(false)}>Set one up in Profile → Security</Link>.</p>
        </form>
      </Modal>
    </>
  )
}
