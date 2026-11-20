'use client'

import { Moon, Sun } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useTheme } from './theme-provider'

/**
 * One-click theme switch: dark by default, light on click.
 * `variant` / `compact` are accepted for existing call sites; the control is
 * always a single icon button.
 */
export function ThemeToggle({
  variant: _variant = 'menu',
  compact = false,
}: {
  variant?: 'menu' | 'segmented'
  compact?: boolean
}) {
  const { theme, toggleTheme } = useTheme()
  const isDark = theme === 'dark'
  const label = isDark ? 'Switch to light theme' : 'Switch to dark theme'

  return (
    <button
      type="button"
      onClick={(event) => toggleTheme({ x: event.clientX, y: event.clientY })}
      aria-label={label}
      title={label}
      aria-pressed={isDark}
      className={`group relative grid shrink-0 place-items-center overflow-hidden rounded-full border border-border bg-surface text-foreground transition-colors duration-200 hover:border-border-strong hover:bg-surface-2 ${
        compact ? 'size-8' : 'size-9'
      }`}
    >
      <AnimatePresence initial={false} mode="wait">
        <motion.span
          key={isDark ? 'moon' : 'sun'}
          initial={{ y: 10, opacity: 0, rotate: -35 }}
          animate={{ y: 0, opacity: 1, rotate: 0 }}
          exit={{ y: -10, opacity: 0, rotate: 35 }}
          transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}
          className="absolute inset-0 grid place-items-center"
        >
          {isDark ? (
            <Moon className="size-4" aria-hidden />
          ) : (
            <Sun className="size-4" aria-hidden />
          )}
        </motion.span>
      </AnimatePresence>
    </button>
  )
}

export default ThemeToggle
