import { useState, type ReactNode } from 'react'
import { Modal } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Checkbox, Field, Textarea } from '@/components/ui/form'
import { InlineAlert } from '@/components/feedback/states'
import { ApiError } from '@/services/api/errors'

export type ConfirmLevel = 'simple' | 'reason' | 'strong'

interface Props {
  open: boolean
  onOpenChange: (o: boolean) => void
  title: string
  /** Names the object and the consequence. */
  description: ReactNode
  /** Destructive buttons are labelled with the verb, e.g. "Delete conversation". */
  confirmLabel: string
  level?: ConfirmLevel
  minReason?: number
  destructive?: boolean
  onConfirm: (reason: string) => Promise<unknown>
}

/** Three confirmation levels (Design Document 13.4). Closes only on success. */
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, level = 'simple', minReason = 10, destructive = true, onConfirm }: Props) {
  const [reason, setReason] = useState('')
  const [ack, setAck] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const needsReason = level !== 'simple'
  const ready = (!needsReason || reason.trim().length >= minReason) && (level !== 'strong' || ack)

  const reset = () => { setReason(''); setAck(false); setErr(null); setBusy(false) }
  const submit = async () => {
    setBusy(true); setErr(null)
    try {
      await onConfirm(reason.trim())
      onOpenChange(false); reset()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Something went wrong. Please try again.')
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onOpenChange={(o) => { if (!busy) { onOpenChange(o); if (!o) reset() } }} title={title} size="sm" dismissible={!busy}
      footer={<>
        <Button variant="secondary" onClick={() => { onOpenChange(false); reset() }} disabled={busy}>Cancel</Button>
        <Button variant={destructive ? 'danger' : 'primary'} onClick={submit} loading={busy} disabled={!ready}>{confirmLabel}</Button>
      </>}>
      <div className="space-y-3">
        <div className="text-sm">{description}</div>
        {needsReason && (
          <Field label="Reason" required hint={`At least ${minReason} characters. Recorded in the audit log.`}>
            {(p) => <Textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} />}
          </Field>
        )}
        {level === 'strong' && <Checkbox checked={ack} onChange={(e) => setAck(e.target.checked)} label="I understand the consequences of this action." />}
        {err && <InlineAlert tone="danger">{err}</InlineAlert>}
      </div>
    </Modal>
  )
}
