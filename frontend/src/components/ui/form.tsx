import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { cn } from '@/utils/cn'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(({ className, ...p }, ref) => (
  <input ref={ref} className={cn('field', className)} {...p} />
))
Input.displayName = 'Input'

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(({ className, ...p }, ref) => (
  <textarea ref={ref} className={cn('field min-h-[80px]', className)} {...p} />
))
Textarea.displayName = 'Textarea'

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(({ className, children, ...p }, ref) => (
  <select ref={ref} className={cn('field pr-8', className)} {...p}>{children}</select>
))
Select.displayName = 'Select'

interface FieldProps {
  label: string
  error?: string
  hint?: string
  required?: boolean
  children: (a: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => ReactNode
  className?: string
}

/** Label + control + hint + error, wired with aria-describedby (Design Document 13.6). */
export function Field({ label, error, hint, required, children, className }: FieldProps) {
  const id = useId()
  const descId = `${id}-d`
  const describedBy = error || hint ? descId : undefined
  return (
    <div className={cn('space-y-1', className)}>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}{required && <span className="text-danger" aria-hidden> *</span>}
      </label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {(error || hint) && (
        <p id={descId} className={cn('text-xs', error ? 'text-danger' : 'text-ink-muted')} role={error ? 'alert' : undefined}>{error ?? hint}</p>
      )}
    </div>
  )
}

// forwardRef is required: react-hook-form's register() hands the field its ref, without which the checkbox is never read or preset.
export const Checkbox = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }>(({ label, className, ...p }, ref) => (
  <label className={cn('inline-flex min-h-[24px] items-center gap-2 text-sm', className)}>
    <input ref={ref} type="checkbox" className="h-4 w-4 rounded border-line accent-primary" {...p} />
    <span>{label}</span>
  </label>
))
Checkbox.displayName = 'Checkbox'

export function Switch({ label, checked, onChange, disabled }: { label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled} onClick={() => onChange(!checked)}
        className={cn('relative h-5 w-9 rounded-full transition-colors disabled:opacity-50', checked ? 'bg-primary' : 'bg-line')}>
        <span className={cn('absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white transition-transform', checked && 'translate-x-4')} />
      </button>
      <span aria-hidden>{label}</span>
    </label>
  )
}
