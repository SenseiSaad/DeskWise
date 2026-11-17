import * as React from 'react'
import { AlertTriangle, Loader2, X } from 'lucide-react'

interface ConfirmDialogProps {
  open: boolean
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
  loading?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  danger = true,
  loading = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  React.useEffect(() => {
    const fn = (e: KeyboardEvent) => e.key === 'Escape' && onCancel()
    if (open) window.addEventListener('keydown', fn)
    return () => window.removeEventListener('keydown', fn)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
      <div className="w-full max-w-md animate-[scale-in_0.2s_ease-out] overflow-hidden rounded-[20px] border border-border bg-surface shadow-2xl">
        <div className="flex items-start justify-between border-b border-border bg-surface-elevated px-6 py-4">
          <div className="flex items-center gap-3">
            <div className={`grid size-10 place-items-center rounded-xl ${danger ? 'bg-danger-soft text-danger' : 'bg-ok-soft text-ok'}`}>
              <AlertTriangle className="size-5" />
            </div>
            <h2 className="text-base font-semibold text-foreground">{title}</h2>
          </div>
          <button onClick={onCancel} aria-label="Close" className="rounded-full p-2 text-muted-foreground hover:bg-surface-2 hover:text-foreground">
            <X className="size-5" />
          </button>
        </div>
        <div className="p-6">
          <p className="text-sm leading-relaxed text-muted-foreground">{message}</p>
        </div>
        <div className="flex justify-end gap-3 border-t border-border bg-surface-elevated px-6 py-4">
          <button
            onClick={onCancel}
            disabled={loading}
            className="inline-flex h-10 items-center justify-center rounded-xl border border-border-strong bg-surface px-4 text-sm font-medium text-foreground hover:bg-surface-2 focus:outline-none focus:ring-2 focus:ring-foreground/20 disabled:opacity-60"
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            disabled={loading}
            className={`inline-flex h-10 items-center justify-center rounded-xl px-5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-60 ${
              danger
                ? 'bg-[#9a3b2c] text-white hover:bg-[#7a2e22] dark:bg-[#b84735] dark:hover:bg-[#cf5642] focus:ring-danger/40'
                : 'bg-primary text-primary-foreground hover:opacity-90 focus:ring-foreground/30'
            }`}
          >
            {loading ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
