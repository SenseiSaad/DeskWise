'use client'

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

export type Theme = 'light' | 'dark'

interface ThemeProviderState {
  theme: Theme
  resolvedTheme: 'light' | 'dark'
  setTheme: (theme: Theme) => void
}

const ThemeProviderContext = createContext<ThemeProviderState>({
  theme: 'light',
  resolvedTheme: 'light',
  setTheme: () => null,
})

const STORAGE_KEY = 'theme'

function applyTheme(theme: Theme) {
  const root = document.documentElement

  root.classList.add('theme-transition')
  root.classList.toggle('dark', theme === 'dark')
  root.classList.toggle('light', theme === 'light')
  root.dataset.theme = theme
  root.style.colorScheme = theme

  // Let CSS settle before enabling hover transitions again.
  window.setTimeout(() => root.classList.remove('theme-transition'), 300)
  return theme
}

export function ThemeProvider({
  children,
  defaultTheme = 'light',
}: {
  children: React.ReactNode
  attribute?: string
  defaultTheme?: Theme
  enableSystem?: boolean
}) {
  const [theme, setThemeState] = useState<Theme>(defaultTheme)
  const [resolvedTheme, setResolvedTheme] = useState<'light' | 'dark'>(defaultTheme)

  // Read the persisted preference on mount. The inline head script has already
  // painted the right class, so this only synchronises React state.
  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    const next: Theme = saved === 'light' || saved === 'dark' ? saved : defaultTheme
    if (saved && saved !== 'light' && saved !== 'dark') {
      window.localStorage.setItem(STORAGE_KEY, next)
    }
    setThemeState(next)
    setResolvedTheme(next)
  }, [defaultTheme])

  useEffect(() => {
    const resolved = applyTheme(theme)
    setResolvedTheme(resolved)
  }, [theme])

  // Follow changes made in another tab.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY) return
      const next = event.newValue
      if (next === 'light' || next === 'dark') setThemeState(next)
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])

  const setTheme = useCallback((next: Theme) => {
    window.localStorage.setItem(STORAGE_KEY, next)
    setThemeState(next)
  }, [])

  const value = useMemo(() => ({ theme, resolvedTheme, setTheme }), [theme, resolvedTheme, setTheme])

  return <ThemeProviderContext.Provider value={value}>{children}</ThemeProviderContext.Provider>
}

export const useTheme = () => {
  const context = useContext(ThemeProviderContext)
  if (context === undefined) throw new Error('useTheme must be used within a ThemeProvider')
  return context
}
