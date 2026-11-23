import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import { Loader2 } from 'lucide-react'
import { cn } from '@/utils/cn'

const variants = cva(
  'inline-flex min-h-[32px] items-center justify-center gap-2 whitespace-nowrap rounded-control px-3 py-1.5 text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-primary text-primary-foreground hover:bg-primary/90',
        secondary: 'border border-line bg-surface text-ink hover:bg-canvas',
        ghost: 'text-ink hover:bg-canvas',
        danger: 'bg-danger text-white hover:bg-danger/90',
        link: 'min-h-0 px-0 py-0 text-primary underline-offset-2 hover:underline',
      },
      size: { sm: 'min-h-[28px] px-2 py-1 text-xs', md: '', icon: 'h-8 w-8 min-h-0 p-0' },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof variants> {
  asChild?: boolean
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild, loading, children, disabled, type = 'button', ...rest }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp ref={ref} type={asChild ? undefined : type} className={cn(variants({ variant, size }), className)}
        disabled={disabled || loading} aria-busy={loading || undefined} {...rest}>
        {asChild ? children : (<>{loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}{children}</>)}
      </Comp>
    )
  },
)
Button.displayName = 'Button'
