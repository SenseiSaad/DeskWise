'use client'

import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { AccessMockup, AuditMockup, ChatMockup, FormMockup } from './mockups'

const CHAPTERS = [
  {
    num: '01',
    title: 'Ask',
    label: 'Instant answers',
    body: 'Ask a question in English, Spanish, French, German, Arabic, Roman Urdu, or other supported languages. Deskwise reads your company documents and answers with the exact page it found it on.',
    visual: <ChatMockup step={2} />,
  },
  {
    num: '02',
    title: 'Generate',
    label: 'Ready-to-send forms',
    body: 'Need a leave request or an HR letter? Deskwise fills in your name, role and dates and gives you a copy-paste-ready document to download as Word or PDF.',
    visual: <FormMockup />,
  },
  {
    num: '03',
    title: 'Protect',
    label: 'Private by default',
    body: 'People only see what belongs to them. Payroll stays with HR, contracts stay with Finance, and nothing is used to train public AI.',
    visual: <AccessMockup />,
  },
  {
    num: '04',
    title: 'Prove',
    label: 'Full history',
    body: 'Every upload, question and download is recorded, so you can always see who did what and when.',
    visual: <AuditMockup />,
  },
]

export function ScrollStory() {
  const [active, setActive] = useState(0)
  const sectionRef = useRef<HTMLElement>(null)
  const railRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<(HTMLLIElement | null)[]>([])

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) setActive(Number((e.target as HTMLElement).dataset.index))
        })
      },
      { rootMargin: '-45% 0px -45% 0px' },
    )
    itemRefs.current.forEach((el) => el && observer.observe(el))

    let raf = 0
    const onScroll = () => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const el = sectionRef.current
        if (!el) return
        const r = el.getBoundingClientRect()
        const total = r.height - window.innerHeight
        const next = Math.min(1, Math.max(0, total > 0 ? -r.top / total : 0))
        // Written straight to the DOM: this runs every frame while scrolling,
        // so a React state update here would re-render the section continuously.
        if (railRef.current) railRef.current.style.height = `${next * 100}%`
      })
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      observer.disconnect()
      cancelAnimationFrame(raf)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  return (
    <section
      id="story"
      ref={sectionRef}
      aria-labelledby="story-heading"
      className="relative scroll-mt-20 border-y border-border bg-surface py-20 sm:py-28"
    >
      <div className="container-page">
        <div className="max-w-2xl">
          <p className="eyebrow">What Deskwise does</p>
          <h2 id="story-heading" className="display-lg mt-5">
            Four things, done simply.
          </h2>
        </div>

        <div className="relative mt-14 grid gap-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] lg:gap-20">
          {/* progress rail */}
          <div aria-hidden className="absolute -left-4 top-0 hidden h-full w-px bg-border xl:block">
            <div
              ref={railRef}
              className="w-px bg-accent will-change-[height]"
              style={{ height: '0%' }}
            />
          </div>

          {/* sticky numeral (desktop) */}
          <div className="hidden lg:block">
            <div className="sticky top-28">
              <div className="relative h-[clamp(8rem,18vw,16rem)] overflow-hidden" aria-hidden>
                <AnimatePresence mode="popLayout" initial={false}>
                  <motion.span
                    key={CHAPTERS[active].num}
                    initial={{ opacity: 0, y: 32, filter: 'blur(6px)' }}
                    animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                    exit={{ opacity: 0, y: -32, filter: 'blur(6px)' }}
                    transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
                    className="absolute inset-0 font-display text-[clamp(8rem,18vw,16rem)] font-bold leading-none tracking-tighter text-foreground block"
                  >
                    {CHAPTERS[active].num}
                  </motion.span>
                </AnimatePresence>
              </div>
              <nav aria-label="Story steps" className="mt-6 grid max-w-sm grid-cols-1 gap-2">
                {CHAPTERS.map((c, i) => {
                  const isCurrent = i === active
                  return (
                    <button
                      key={c.num}
                      type="button"
                      onClick={() => {
                        setActive(i)
                        itemRefs.current[i]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
                      }}
                      aria-current={isCurrent ? 'step' : undefined}
                      className={`group flex min-h-12 w-full cursor-pointer items-center gap-3 rounded-xl border px-3.5 py-2.5 text-left transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 ${
                        isCurrent
                          ? 'border-accent/60 bg-surface-elevated text-foreground shadow-sm'
                          : 'border-border bg-surface-elevated/45 text-muted-foreground hover:border-border-strong hover:bg-surface-elevated hover:text-foreground'
                      }`}
                    >
                      <span
                        className={`grid size-8 shrink-0 place-items-center rounded-lg font-mono text-xs font-semibold transition-colors ${
                          isCurrent
                            ? 'bg-accent text-accent-foreground'
                            : 'bg-surface-2 text-muted-foreground group-hover:text-foreground'
                        }`}
                      >
                        {c.num}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13px] font-semibold leading-tight tracking-tight">
                          {c.title}
                        </span>
                        <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                          {c.label}
                        </span>
                      </span>
                      <span
                        aria-hidden
                        className={`h-1.5 w-1.5 shrink-0 rounded-full transition-colors ${
                          isCurrent ? 'bg-accent' : 'bg-border-strong group-hover:bg-muted-foreground'
                        }`}
                      />
                    </button>
                  )
                })}
              </nav>
            </div>
          </div>

          <ol className="space-y-24 lg:space-y-[40vh]">
            {CHAPTERS.map((c, i) => (
              <li
                key={c.num}
                ref={(el) => {
                  itemRefs.current[i] = el
                }}
                data-index={i}
                aria-label={`${c.num} ${c.title}`}
                className={`transition-opacity duration-300 motion-reduce:transition-none lg:py-[8vh] ${
                  i === active ? 'lg:opacity-100' : 'lg:opacity-40'
                }`}
              >
                <span aria-hidden className="font-display text-7xl font-bold leading-none tracking-tighter text-foreground lg:hidden">
                  {c.num}
                </span>
                <div className="mt-4 border-t border-foreground/80 pt-5 lg:mt-0">
                  <h3 className="text-3xl font-semibold tracking-tight">{c.title}</h3>
                  <p className="mt-1 text-sm font-medium text-accent">{c.label}</p>
                  <p className="mt-4 max-w-lg text-base leading-relaxed text-muted-foreground">{c.body}</p>
                  <motion.div
                    animate={{
                      opacity: i === active ? 1 : 0.65,
                      y: i === active ? 0 : 8,
                      scale: i === active ? 1 : 0.98,
                    }}
                    transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
                    className="mt-6 max-w-md"
                  >
                    {c.visual}
                  </motion.div>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  )
}

export default ScrollStory
