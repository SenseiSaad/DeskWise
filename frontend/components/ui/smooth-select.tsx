'use client'

import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'motion/react'
import { Check, ChevronDown } from 'lucide-react'

const EASE = [0.22, 1, 0.36, 1] as const

export interface SmoothSelectOption<T extends string = string> {
  value: T
  label: string
  description?: string
  badge?: string
  dot?: 'online' | 'offline' | 'muted' | 'amber'
  disabled?: boolean
}

interface SmoothSelectProps<T extends string = string> {
  id?: string
  value: T
  onChange: (value: T) => void
  options: SmoothSelectOption<T>[]
  placeholder?: string
  disabled?: boolean
  className?: string
  menuClassName?: string
  size?: 'sm' | 'md' | 'pill'
  leadingIcon?: ReactNode
  ariaLabel?: string
  align?: 'left' | 'right'
}

const DOT_CLASSES: Record<NonNullable<SmoothSelectOption['dot']>, string> = {
  online: 'bg-emerald-500 shadow-[0_0_0_2px_rgba(16,185,129,0.18)]',
  amber: 'bg-amber-500 shadow-[0_0_0_2px_rgba(245,158,11,0.18)]',
  offline: 'bg-muted-foreground/50',
  muted: 'bg-muted-foreground/40',
}

export function SmoothSelect<T extends string = string>({
  id,
  value,
  onChange,
  options,
  placeholder = 'Select an option',
  disabled = false,
  className = '',
  menuClassName = '',
  size = 'md',
  leadingIcon,
  ariaLabel,
  align = 'left',
}: SmoothSelectProps<T>) {
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState<number>(-1)
  const [coords, setCoords] = useState<{
    top: number
    left: number
    width: number
    openUpward: boolean
    maxHeight: number
  } | null>(null)

  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const listboxId = useId()

  const selected = options.find((opt) => opt.value === value)

  const updatePosition = useCallback(() => {
    const el = triggerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const viewportH = window.innerHeight
    const viewportW = window.innerWidth
    const spaceBelow = viewportH - rect.bottom - 12
    const spaceAbove = rect.top - 12
    const estimatedMenuHeight = Math.min(options.length * 46 + 16, 290)
    const openUpward = spaceBelow < Math.min(180, estimatedMenuHeight) && spaceAbove > spaceBelow
    const availableHeight = openUpward ? spaceAbove : spaceBelow
    const minMenuWidth = size === 'pill' ? Math.max(rect.width, 240) : Math.max(rect.width, 180)
    const width = Math.min(minMenuWidth, viewportW - 24)
    let left = align === 'right' ? rect.right - width : rect.left
    left = Math.max(12, Math.min(left, viewportW - width - 12))

    setCoords({
      top: openUpward ? rect.top - 6 : rect.bottom + 6,
      left,
      width,
      openUpward,
      maxHeight: Math.max(120, Math.min(290, availableHeight)),
    })
  }, [align, options.length, size])

  useLayoutEffect(() => {
    if (!open) return
    updatePosition()
    const selectedIdx = options.findIndex((o) => o.value === value && !o.disabled)
    setActiveIndex(selectedIdx >= 0 ? selectedIdx : options.findIndex((o) => !o.disabled))
  }, [open, options, updatePosition, value])

  useEffect(() => {
    if (!open) return
    const onResizeOrScroll = () => updatePosition()
    window.addEventListener('resize', onResizeOrScroll)
    window.addEventListener('scroll', onResizeOrScroll, true)
    return () => {
      window.removeEventListener('resize', onResizeOrScroll)
      window.removeEventListener('scroll', onResizeOrScroll, true)
    }
  }, [open, updatePosition])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent | TouchEvent) => {
      const target = e.target as Node | null
      if (!target) return
      if (triggerRef.current?.contains(target)) return
      if (menuRef.current?.contains(target)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('touchstart', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('touchstart', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const moveFocus = (delta: 1 | -1) => {
    if (!options.length) return
    let idx = activeIndex
    for (let step = 0; step < options.length; step++) {
      idx = (idx + delta + options.length) % options.length
      if (!options[idx]?.disabled) {
        setActiveIndex(idx)
        return
      }
    }
  }

  const handleKeyDown = (e: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (disabled) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) {
        setOpen(true)
      } else {
        moveFocus(1)
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) {
        setOpen(true)
      } else {
        moveFocus(-1)
      }
    } else if (e.key === 'Enter' || e.key === ' ') {
      if (open) {
        e.preventDefault()
        const opt = options[activeIndex]
        if (opt && !opt.disabled) {
          onChange(opt.value)
          setOpen(false)
        }
      }
    } else if (e.key === 'Tab' && open) {
      setOpen(false)
    }
  }

  const triggerSizeClass =
    size === 'pill'
      ? 'h-8 rounded-full border-border-strong bg-surface px-3 text-[11px] font-medium hover:border-foreground/50'
      : size === 'sm'
      ? 'h-10 rounded-xl border-border-strong bg-surface-elevated px-3.5 text-xs hover:border-foreground/50'
      : 'h-11 rounded-xl border-border-strong bg-surface-elevated px-3.5 text-xs hover:border-foreground'

  const menu =
    typeof document !== 'undefined'
      ? createPortal(
          <AnimatePresence>
            {open && coords && (
              <motion.div
                ref={menuRef}
                id={listboxId}
                role="listbox"
                aria-label={ariaLabel}
                initial={{ opacity: 0, y: coords.openUpward ? 6 : -6, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: coords.openUpward ? 4 : -4, scale: 0.97 }}
                transition={{ duration: 0.16, ease: EASE }}
                style={{
                  position: 'fixed',
                  left: coords.left,
                  width: coords.width,
                  ...(coords.openUpward
                    ? { bottom: window.innerHeight - coords.top }
                    : { top: coords.top }),
                  maxHeight: coords.maxHeight,
                  transformOrigin: coords.openUpward ? 'bottom center' : 'top center',
                }}
                className={`z-[120] overflow-y-auto overscroll-contain rounded-2xl border border-border-strong bg-surface-elevated p-1.5 shadow-xl shadow-black/15 dark:shadow-black/50 backdrop-blur-md ${menuClassName}`}
              >
                {options.map((opt, idx) => {
                  const isSelected = opt.value === value
                  const isActive = idx === activeIndex
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      disabled={opt.disabled}
                      onMouseEnter={() => !opt.disabled && setActiveIndex(idx)}
                      onClick={() => {
                        if (opt.disabled) return
                        onChange(opt.value)
                        setOpen(false)
                        triggerRef.current?.focus()
                      }}
                      className={`flex w-full items-start gap-2.5 rounded-xl px-2.5 py-2 text-left transition-colors duration-150 ${
                        opt.disabled
                          ? 'cursor-not-allowed opacity-45'
                          : isSelected
                          ? 'bg-surface-2 text-foreground'
                          : isActive
                          ? 'bg-surface text-foreground'
                          : 'text-foreground hover:bg-surface'
                      }`}
                    >
                      {opt.dot && (
                        <span
                          className={`mt-1.5 size-2 shrink-0 rounded-full ${DOT_CLASSES[opt.dot]}`}
                        />
                      )}
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2">
                          <span className="truncate text-xs font-medium text-foreground">
                            {opt.label}
                          </span>
                          {opt.badge && (
                            <span className="shrink-0 rounded-full bg-surface-2 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                              {opt.badge}
                            </span>
                          )}
                        </span>
                        {opt.description && (
                          <span className="mt-0.5 block text-[11px] leading-snug text-muted-foreground">
                            {opt.description}
                          </span>
                        )}
                      </span>
                      <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center">
                        {isSelected && <Check className="size-3.5 text-foreground" />}
                      </span>
                    </button>
                  )
                })}
              </motion.div>
            )}
          </AnimatePresence>,
          document.body
        )
      : null

  return (
    <>
      <button
        ref={triggerRef}
        id={id}
        type="button"
        role="combobox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => !disabled && setOpen((v) => !v)}
        onKeyDown={handleKeyDown}
        className={`group inline-flex w-full items-center justify-between gap-2 border text-left text-foreground outline-none transition-all duration-150 active:scale-[0.995] focus-visible:border-foreground focus-visible:ring-2 focus-visible:ring-foreground/15 disabled:cursor-not-allowed disabled:opacity-60 ${
          open ? 'border-foreground ring-2 ring-foreground/10' : ''
        } ${triggerSizeClass} ${className}`}
      >
        <span className="flex min-w-0 flex-1 items-center gap-2">
          {leadingIcon && <span className="shrink-0 text-muted-foreground">{leadingIcon}</span>}
          {selected?.dot && (
            <span className={`size-2 shrink-0 rounded-full ${DOT_CLASSES[selected.dot]}`} />
          )}
          <span className={`truncate ${selected ? 'text-foreground' : 'text-muted-foreground'}`}>
            {selected ? selected.label : placeholder}
          </span>
        </span>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.18, ease: EASE }}
          className="shrink-0 text-muted-foreground transition-colors group-hover:text-foreground"
        >
          <ChevronDown className="size-3.5" />
        </motion.span>
      </button>
      {menu}
    </>
  )
}

export function SmoothCollapse({
  open,
  children,
  className = '',
}: {
  open: boolean
  children: ReactNode
  className?: string
}) {
  return (
    <AnimatePresence initial={false}>
      {open && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: 'auto', opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.24, ease: EASE }}
          className={`overflow-hidden ${className}`}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export function SmoothDialogFrame({
  onClose,
  children,
  maxWidthClass = 'max-w-lg',
  panelClassName = '',
  ariaLabel,
}: {
  onClose: () => void
  children: ReactNode
  maxWidthClass?: string
  panelClassName?: string
  ariaLabel?: string
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18, ease: EASE }}
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-[2px]"
    >
      <motion.div
        initial={{ opacity: 0, y: 12, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.97 }}
        transition={{ duration: 0.2, ease: EASE }}
        onClick={(e) => e.stopPropagation()}
        className={`w-full overflow-hidden rounded-3xl border border-border bg-surface-elevated shadow-2xl shadow-black/25 ${maxWidthClass} ${panelClassName}`}
      >
        {children}
      </motion.div>
    </motion.div>
  )
}

export function SmoothModal({
  open,
  onClose,
  children,
  maxWidthClass = 'max-w-lg',
  panelClassName = '',
  ariaLabel,
}: {
  open: boolean
  onClose: () => void
  children: ReactNode
  maxWidthClass?: string
  panelClassName?: string
  ariaLabel?: string
}) {
  return (
    <AnimatePresence>
      {open && (
        <SmoothDialogFrame
          onClose={onClose}
          maxWidthClass={maxWidthClass}
          panelClassName={panelClassName}
          ariaLabel={ariaLabel}
        >
          {children}
        </SmoothDialogFrame>
      )}
    </AnimatePresence>
  )
}
