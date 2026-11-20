'use client'

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

export type Theme = 'light' | 'dark'

interface ThemeProviderState {
  theme: Theme
  resolvedTheme: 'light' | 'dark'
  setTheme: (theme: Theme) => void
  /** Flip dark ↔ light. Pass the click point for the circular reveal origin. */
  toggleTheme: (point?: { x: number; y: number }) => void
}

const ThemeProviderContext = createContext<ThemeProviderState>({
  theme: 'dark',
  resolvedTheme: 'dark',
  setTheme: () => null,
  toggleTheme: () => null,
})

const STORAGE_KEY = 'theme'

type ViewTransitionDocument = Document & {
  startViewTransition?: (callback: () => void) => { finished: Promise<void> }
}

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** Write the theme to the DOM immediately (no React round-trip). */
function applyTheme(theme: Theme) {
  const root = document.documentElement
  root.classList.toggle('dark', theme === 'dark')
  root.classList.toggle('light', theme === 'light')
  root.dataset.theme = theme
  root.style.colorScheme = theme

  // Browsers without the View Transitions API get a short colour crossfade.
  if (typeof (document as ViewTransitionDocument).startViewTransition === 'undefined') {
    root.classList.add('theme-transition')
    window.setTimeout(() => root.classList.remove('theme-transition'), 320)
  }
}

export function ThemeProvider({
  children,
  defaultTheme = 'dark',
}: {
  children: React.ReactNode
  attribute?: string
  defaultTheme?: Theme
  enableSystem?: boolean
}) {
  const [theme, setThemeState] = useState<Theme>(defaultTheme)
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(defaultTheme)

  // The inline head script has already painted the right class; this only
  // synchronises React state with it.
  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    const next: Theme = saved === 'light' ? 'light' : 'dark'
    setThemeState(next)
    setResolvedTheme(next)
  }, [])

  const setTheme = useCallback((next: Theme) => {
    window.localStorage.setItem(STORAGE_KEY, next)
    applyTheme(next)
    setThemeState(next)
    setResolvedTheme(next)
  }, [])

  const toggleTheme = useCallback(
    (point?: { x: number; y: number }) => {
      const next: Theme = theme === 'dark' ? 'light' : 'dark'
      const doc = document as ViewTransitionDocument

      if (!doc.startViewTransition || prefersReducedMotion()) {
        setTheme(next)
        return
      }

      // Origin + radius for the circular reveal, measured from the click.
      const x = point?.x ?? window.innerWidth / 2
      const y = point?.y ?? 0
      const radius = Math.ceil(
        Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y)),
      )
      const root = document.documentElement
      root.style.setProperty('--theme-x', `${x}px`)
      root.style.setProperty('--theme-y', `${y}px`)
      root.style.setProperty('--theme-r', `${radius}px`)

      // setTheme mutates the DOM class synchronously, which is what the
      // browser snapshots — React state catches up in the same tick.
      doc.startViewTransition(() => setTheme(next))
    },
    [theme, setTheme],
  )

  // Follow changes made in another tab.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY) return
      if (event.newValue === 'light' || event.newValue === 'dark') {
        applyTheme(event.newValue)
        setThemeState(event.newValue)
        setResolvedTheme(event.newValue)
      }
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const value = useMemo(
    () => ({ theme, resolvedTheme, setTheme, toggleTheme }),
    [theme, resolvedTheme, setTheme, toggleTheme],
  )

  return <ThemeProviderContext.Provider value={value}>{children}</ThemeProviderContext.Provider>
}

export const useTheme = () => {
  const context = useContext(ThemeProviderContext)
  if (context === undefined) throw new Error('useTheme must be used within a ThemeProvider')
  return context
}
