'use client'

import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { AccessMockup, AuditMockup, ChatMockup, FormMockup } from './mockups'

const CHAPTERS = [
  {
    num: '01',
    title: 'Ask',
    label: 'Instant answers',
    body: 'Ask a question in plain English or Roman Urdu. Deskwise reads your company documents and answers with the exact page it found it on.',
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
  const [progress, setProgress] = useState(0)
  const sectionRef = useRef<HTMLElement>(null)
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
        setProgress(Math.min(1, Math.max(0, total > 0 ? -r.top / total : 0)))
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
              className="w-px bg-accent transition-[height] duration-200 ease-out"
              style={{ height: `${progress * 100}%` }}
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
              <div className="mt-6 flex gap-2">
                {CHAPTERS.map((c, i) => (
                  <motion.button
                    key={c.num}
                    type="button"
                    onClick={() => itemRefs.current[i]?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
                    animate={{
                      width: i === active ? 40 : 16,
                      backgroundColor: i === active ? 'var(--accent)' : 'var(--border-strong)',
                    }}
                    transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
                    className="h-1.5 rounded-full cursor-pointer focus:outline-none"
                    aria-label={`Jump to chapter ${c.num}`}
                  />
                ))}
              </div>
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
