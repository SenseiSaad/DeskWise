'use client'

import { useEffect, type ReactNode } from 'react'
import { usePathname } from 'next/navigation'
import Lenis from 'lenis'

export function SmoothScroll({ children }: { children: ReactNode }) {
  const pathname = usePathname()
  // The workspace is an app shell with its own scroll panes (chat feeds,
  // sidebars). Lenis hijacks wheel/touch at the document level and would stop
  // those panes from scrolling, so it only runs on the marketing pages.
  const isAppRoute = pathname?.startsWith('/workspace') || pathname?.startsWith('/auth')

  useEffect(() => {
    if (isAppRoute) return

    // Respect user's reduced motion preference
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      return
    }

    const lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)), // Buttery exponential easing
      orientation: 'vertical',
      gestureOrientation: 'vertical',
      smoothWheel: true,
      wheelMultiplier: 0.9,
      touchMultiplier: 1.5,
    })

    function raf(time: number) {
      lenis.raf(time)
      requestAnimationFrame(raf)
    }

    const rafId = requestAnimationFrame(raf)

    // Smooth scroll for anchor clicks (e.g. #story, /#story, #pricing)
    const handleAnchorClick = (e: MouseEvent) => {
      const target = (e.target as HTMLElement).closest('a')
      if (!target) return
      const href = target.getAttribute('href')
      if (!href) return

      let hash = ''
      if (href.startsWith('#') && href.length > 1) {
        hash = href
      } else if (href.startsWith('/#') && window.location.pathname === '/') {
        hash = href.slice(1)
      }

      if (hash) {
        try {
          const el = document.querySelector(hash)
          if (el) {
            e.preventDefault()
            window.history.pushState(null, '', hash)
            lenis.scrollTo(el as HTMLElement, { offset: -70, duration: 1.2 })
          }
        } catch {
          // ignore invalid selector
        }
      }
    }

    document.addEventListener('click', handleAnchorClick)

    return () => {
      cancelAnimationFrame(rafId)
      document.removeEventListener('click', handleAnchorClick)
      lenis.destroy()
    }
  }, [isAppRoute])

  return <>{children}</>
}

export default SmoothScroll
