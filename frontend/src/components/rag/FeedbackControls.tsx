import { useMutation } from '@tanstack/react-query'
import { Flag, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { chatApi, type FeedbackBody } from '@/services/api/chatApi'
import { ApiError } from '@/services/api/errors'
import { Can } from '@/app/guards'
import { Button } from '@/components/ui/button'
import { Modal } from '@/components/ui/dialog'
import { Field, Textarea } from '@/components/ui/form'
import { InlineAlert } from '@/components/feedback/states'

const CATEGORIES: { value: NonNullable<FeedbackBody['category']>; label: string }[] = [
  { value: 'incorrect', label: 'Incorrect' }, { value: 'outdated', label: 'Outdated' }, { value: 'unsafe', label: 'Unsafe' },
  { value: 'missing_source', label: 'Missing source' }, { value: 'wrong_version', label: 'Wrong version' }, { value: 'access', label: 'Access problem' },
  { value: 'document_error', label: 'Document error' }, { value: 'other', label: 'Other' },
]

export function ReportDialog({ open, onOpenChange, target, initial }: { open: boolean; onOpenChange: (o: boolean) => void; target: Pick<FeedbackBody, 'message_id' | 'search_id'>; initial?: FeedbackBody['category'] }) {
  const [cat, setCat] = useState<NonNullable<FeedbackBody['category']>>(initial ?? 'incorrect')
  const [comment, setComment] = useState('')
  const m = useMutation({
    mutationFn: () => chatApi.feedback({ ...target, category: cat, comment: comment.trim() || undefined }),
    onSuccess: () => { toast.success('Thanks, your feedback was sent to the content team.'); onOpenChange(false); setComment('') },
  })
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Report a problem" size="sm" description="Do not include customer personal data."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button loading={m.isPending} onClick={() => m.mutate()}>Send report</Button></>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); m.mutate() }}>
        <fieldset><legend className="mb-1 text-sm font-medium">What is wrong?</legend>
          <div className="grid grid-cols-2 gap-1">{CATEGORIES.map((c) => (
            <label key={c.value} className="flex min-h-[28px] items-center gap-2 text-sm"><input type="radio" name="cat" className="accent-primary" checked={cat === c.value} onChange={() => setCat(c.value)} />{c.label}</label>
          ))}</div></fieldset>
        <Field label="Comment" hint={`${comment.length}/2000`}>{(p) => <Textarea {...p} maxLength={2000} value={comment} onChange={(e) => setComment(e.target.value)} />}</Field>
        {m.isError && <InlineAlert tone="danger">{(m.error as ApiError).message}</InlineAlert>}
      </form>
    </Modal>
  )
}

/** Thumbs record immediately (optimistic); buttons stay disabled until the response arrives. */
export function RatingButtons({ target }: { target: Pick<FeedbackBody, 'message_id' | 'search_id'> }) {
  const [rated, setRated] = useState<-1 | 1 | null>(null)
  const [report, setReport] = useState(false)
  const m = useMutation({
    mutationFn: (rating: -1 | 1) => chatApi.feedback({ ...target, rating, category: 'rating' }),
    onMutate: (r) => setRated(r),
    onError: (e) => { setRated(null); toast.error((e as ApiError).message) },
    onSuccess: () => toast.success('Thanks, your feedback was sent to the content team.'),
  })
  return (
    <Can permission="feedback.submit">
      <span className="inline-flex items-center gap-1">
        <Button variant="ghost" size="icon" aria-label="Helpful" aria-pressed={rated === 1} disabled={m.isPending || rated !== null} onClick={() => m.mutate(1)}><ThumbsUp className="h-4 w-4" aria-hidden /></Button>
        <Button variant="ghost" size="icon" aria-label="Not helpful" aria-pressed={rated === -1} disabled={m.isPending || rated !== null} onClick={() => m.mutate(-1)}><ThumbsDown className="h-4 w-4" aria-hidden /></Button>
        <Button variant="ghost" size="sm" onClick={() => setReport(true)}><Flag className="h-3.5 w-3.5" aria-hidden />Report…</Button>
      </span>
      <ReportDialog open={report} onOpenChange={setReport} target={target} />
    </Can>
  )
}
