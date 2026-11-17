'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Info } from 'lucide-react'

// Small click-to-open info popover for inline notices (beta lock, data use).
export function InfoPopover({
  label = 'More information',
  children,
  className = '',
}: {
  label?: string
  children: ReactNode
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <span ref={ref} className={`relative inline-flex ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={label}
        aria-expanded={open}
        className="grid size-6 shrink-0 place-items-center rounded-full border border-border-strong bg-surface-elevated text-muted-foreground transition hover:border-foreground hover:text-foreground"
      >
        <Info className="size-3.5" aria-hidden />
      </button>
      {open && (
        <div
          role="dialog"
          className="absolute right-0 top-8 z-50 w-72 rounded-2xl border border-border-strong bg-surface-elevated p-3 text-left text-[11px] leading-relaxed text-muted-foreground shadow-lg"
        >
          {children}
        </div>
      )}
    </span>
  )
}
