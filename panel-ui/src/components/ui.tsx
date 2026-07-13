import React, { useEffect, useId, useRef } from 'react'
import { motion } from 'framer-motion'
import { ChevronDown, X } from 'lucide-react'

// ---------------------------------------------------------------- Card
export function Card({
  children,
  className = '',
  hover = false,
  onClick,
}: {
  children: React.ReactNode
  className?: string
  hover?: boolean
  onClick?: () => void
}) {
  if (hover || onClick) {
    return (
      <motion.div
        whileHover={{ scale: 1.01, y: -3 }}
        whileTap={onClick ? { scale: 0.99 } : undefined}
        className={`glass-card p-6 ${onClick ? 'cursor-pointer' : ''} ${className}`}
        onClick={onClick}
      >
        {children}
      </motion.div>
    )
  }
  return <div className={`glass-card p-6 ${className}`}>{children}</div>
}

// ---------------------------------------------------------------- Button
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md' | 'lg'
export function Button({
  children,
  variant = 'primary',
  size = 'md',
  isLoading = false,
  leftIcon,
  className = '',
  disabled,
  type = 'button',
  onClick,
  title,
}: {
  children?: React.ReactNode
  variant?: Variant
  size?: Size
  isLoading?: boolean
  leftIcon?: React.ReactNode
  className?: string
  disabled?: boolean
  type?: 'button' | 'submit' | 'reset'
  onClick?: React.MouseEventHandler<HTMLButtonElement>
  title?: string
}) {
  const base =
    'inline-flex items-center justify-center font-medium transition-all duration-300 rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900'
  const variants: Record<Variant, string> = {
    primary: 'glass-button',
    secondary: 'bg-white/10 hover:bg-white/20 border border-white/20 text-white',
    ghost: 'bg-transparent hover:bg-white/10 text-white/80 hover:text-white',
    danger: 'bg-red-500/80 hover:bg-red-500 border border-red-400/30 text-white',
  }
  const sizes: Record<Size, string> = {
    sm: 'px-3 py-1.5 text-sm min-h-[36px]',
    md: 'px-5 py-2.5 text-sm min-h-[44px]',
    lg: 'px-6 py-3 text-base min-h-[52px]',
  }
  const isDisabled = disabled || isLoading
  return (
    <motion.button
      whileHover={isDisabled ? undefined : { scale: 1.02 }}
      whileTap={isDisabled ? undefined : { scale: 0.98 }}
      className={`${base} ${variants[variant]} ${sizes[size]} ${className} ${
        isDisabled ? 'opacity-50 cursor-not-allowed' : ''
      }`}
      disabled={isDisabled}
      type={type}
      onClick={onClick}
      title={title}
    >
      {isLoading && (
        <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
      )}
      {!isLoading && leftIcon && <span className="mr-2">{leftIcon}</span>}
      {children}
    </motion.button>
  )
}

// ---------------------------------------------------------------- Input
export function Input({
  label,
  error,
  helperText,
  required,
  leftIcon,
  className = '',
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & {
  label?: string
  error?: string
  helperText?: string
  leftIcon?: React.ReactNode
}) {
  const genId = useId()
  const id = props.id || genId
  const describedBy = error ? `${id}-err` : helperText ? `${id}-help` : undefined
  return (
    <div className="w-full">
      {label && (
        <label htmlFor={id} className="block text-sm font-medium text-white/70 mb-2">
          {label}
          {required && (
            <span className="text-primary-400 ml-0.5" aria-hidden="true">
              *
            </span>
          )}
        </label>
      )}
      <div className="relative">
        {leftIcon && (
          <div className="absolute left-4 top-1/2 -translate-y-1/2 text-white/40" aria-hidden="true">
            {leftIcon}
          </div>
        )}
        <input
          id={id}
          aria-required={required || undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={`glass-input ${leftIcon ? 'pl-11' : ''} ${error ? 'border-red-400/50' : ''} ${className}`}
          {...props}
        />
      </div>
      {helperText && !error && (
        <p id={`${id}-help`} className="mt-1.5 text-sm text-white/50">
          {helperText}
        </p>
      )}
      {error && (
        <p id={`${id}-err`} className="mt-1.5 text-sm text-red-400" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- Textarea
export function Textarea({
  label,
  className = '',
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label?: string }) {
  const genId = useId()
  const id = props.id || genId
  return (
    <div className="w-full">
      {label && (
        <label htmlFor={id} className="block text-sm font-medium text-white/70 mb-2">
          {label}
        </label>
      )}
      <textarea id={id} className={`glass-input min-h-[90px] resize-y ${className}`} {...props} />
    </div>
  )
}

// ---------------------------------------------------------------- Select
export function Select({
  label,
  options,
  className = '',
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string
  options: { value: string; label: string }[]
}) {
  const genId = useId()
  const id = props.id || genId
  return (
    <div className="w-full">
      {label && (
        <label htmlFor={id} className="block text-sm font-medium text-white/70 mb-2">
          {label}
        </label>
      )}
      <div className="relative">
        <select
          id={id}
          className={`glass-input appearance-none pr-10 cursor-pointer ${className}`}
          {...props}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/40 pointer-events-none"
          aria-hidden="true"
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- Badge
type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info'
export function Badge({
  children,
  variant = 'default',
}: {
  children: React.ReactNode
  variant?: BadgeVariant
}) {
  const variants: Record<BadgeVariant, string> = {
    default: 'bg-white/10 text-white/80 border-white/20',
    success: 'bg-green-500/20 text-green-200 border-green-500/30',
    warning: 'bg-amber-500/20 text-amber-200 border-amber-500/30',
    danger: 'bg-red-500/20 text-red-200 border-red-500/30',
    info: 'bg-blue-500/20 text-blue-200 border-blue-500/30',
  }
  return (
    <span
      className={`inline-flex items-center gap-1 font-medium rounded-full border px-2.5 py-1 text-xs ${variants[variant]}`}
    >
      {children}
    </span>
  )
}

const STATUS_VARIANT: Record<string, BadgeVariant> = {
  active: 'success',
  pending: 'info',
  provisioning: 'warning',
  suspended: 'warning',
  offline: 'default',
  failed: 'danger',
  decommissioned: 'default',
}
export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={STATUS_VARIANT[status] || 'default'}>{status}</Badge>
}

// ---------------------------------------------------------------- Modal
export function Modal({
  open,
  onClose,
  title,
  children,
  wide = false,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  wide?: boolean
}) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const previouslyFocused = document.activeElement as HTMLElement | null
    document.body.style.overflow = 'hidden'
    // Move focus into the dialog for screen-reader + keyboard users.
    const first = panelRef.current?.querySelector<HTMLElement>(
      'input, button, textarea, select, [tabindex]:not([tabindex="-1"])',
    )
    first?.focus()

    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Tab' && panelRef.current) {
        // Simple focus trap
        const focusables = Array.from(
          panelRef.current.querySelectorAll<HTMLElement>(
            'input, button, textarea, select, a[href], [tabindex]:not([tabindex="-1"])',
          ),
        ).filter((el) => !el.hasAttribute('disabled'))
        if (focusables.length === 0) return
        const firstEl = focusables[0]
        const lastEl = focusables[focusables.length - 1]
        if (e.shiftKey && document.activeElement === firstEl) {
          e.preventDefault()
          lastEl.focus()
        } else if (!e.shiftKey && document.activeElement === lastEl) {
          e.preventDefault()
          firstEl.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      previouslyFocused?.focus()
    }
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 backdrop-blur-sm p-4 sm:p-8"
      onClick={onClose}
    >
      <motion.div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        initial={{ opacity: 0, y: 20, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        className={`glass-card w-full ${wide ? 'max-w-3xl' : 'max-w-lg'} my-auto`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-6 border-b border-white/10">
          <h2 id={titleId} className="text-lg font-bold text-white">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="p-2 rounded-lg text-white/50 hover:text-white hover:bg-white/10 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6">{children}</div>
      </motion.div>
    </div>
  )
}

// ---------------------------------------------------------------- Toggle
export function SegmentToggle({
  value,
  options,
  onChange,
}: {
  value: string
  options: { value: string; label: string }[]
  onChange: (v: string) => void
}) {
  return (
    <div className="inline-flex rounded-xl bg-white/5 border border-white/10 p-1">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-all ${
            value === o.value
              ? 'bg-gradient-to-r from-indigo-500 to-indigo-600 text-white shadow-lg shadow-indigo-500/20'
              : 'text-white/60 hover:text-white'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- misc
export function Spinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-8 h-8 border-2 border-white/20 border-t-primary-400 rounded-full animate-spin" />
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon: React.ReactNode
  title: string
  hint?: string
  action?: React.ReactNode
}) {
  return (
    <div className="text-center py-16">
      <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-white/40">
        {icon}
      </div>
      <p className="text-white/80 font-medium">{title}</p>
      {hint && <p className="text-white/40 text-sm mt-1">{hint}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z')
  const s = Math.floor((Date.now() - d.getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}
