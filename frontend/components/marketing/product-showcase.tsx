'use client'

import { useRef, useState } from 'react'
import {
  FileText,
  LockKeyhole,
  Play,
  Pause,
  Maximize2,
  Sparkles,
  ShieldCheck,
  CheckCircle2,
  ArrowRight,
} from 'lucide-react'
import Link from 'next/link'
import { Reveal } from '@/components/reveal'

const FEATURES = [
  {
    num: '01',
    title: 'Ask in plain language, get exact answers',
    description:
      'No more digging through endless folders or 50-page PDFs. Ask in everyday English or Roman Urdu, and get instant answers with the exact page and paragraph cited.',
    badge: 'AI Knowledge Search',
    icon: Sparkles,
  },
  {
    num: '02',
    title: 'Ready-to-send forms, letters & requests',
    description:
      'Need an official leave request, expense report, or HR notice? Deskwise generates complete, formatted documents with your name, date, and company details filled in—ready to download as DOCX or PDF.',
    badge: 'Smart Document Generator',
    icon: FileText,
  },
  {
    num: '03',
    title: 'Automatic privacy: employees only see what they should',
    description:
      'Confidential executive notes and payroll records stay strictly protected. Team members can only search and view files that belong to their department or permissions.',
    badge: 'Zero-Leak Security',
    icon: LockKeyhole,
  },
]

export function ProductShowcase() {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [isPlaying, setIsPlaying] = useState(true)

  function togglePlay() {
    if (!videoRef.current) return
    if (isPlaying) {
      videoRef.current.pause()
      setIsPlaying(false)
    } else {
      videoRef.current.play()
      setIsPlaying(true)
    }
  }

  function handleFullscreen() {
    if (!videoRef.current) return
    if (videoRef.current.requestFullscreen) {
      videoRef.current.requestFullscreen()
    }
  }

  return (
    <section
      id="features"
      className="relative overflow-hidden border-y border-border bg-[#0d0d0f] py-20 text-white sm:py-28"
      aria-labelledby="features-heading"
    >
      {/* Background glow effects */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[32rem] w-[50rem] -translate-x-1/2 rounded-full bg-[radial-gradient(ellipse_at_center,rgba(255,91,36,0.12),transparent_70%)] blur-3xl"
      />

      <div className="container-page">
        {/* Section Header */}
        <div className="mx-auto max-w-3xl text-center">
          <Reveal>
            <div className="inline-flex items-center gap-2 rounded-full border border-[#ff5b24]/30 bg-[#ff5b24]/10 px-3 py-1 text-xs font-semibold tracking-wide text-[#ff7747]">
              <Sparkles className="size-3.5" aria-hidden />
              <span>Simple & Powerful</span>
            </div>
            <h2
              id="features-heading"
              className="mt-4 text-3xl font-semibold tracking-tight text-white sm:text-4xl lg:text-5xl"
            >
              See how easy it is to manage{' '}
              <span className="text-[#ff5b24]">company knowledge.</span>
            </h2>
            <p className="mt-4 text-base leading-relaxed text-zinc-400 sm:text-lg">
              No technical training required. Your team simply asks questions, downloads official documents, and stays aligned without security worries.
            </p>
          </Reveal>
        </div>

        {/* Video Player Showcase */}
        <Reveal delay={100}>
          <div className="relative mx-auto mt-12 max-w-5xl">
            {/* Device Frame */}
            <div className="relative overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950/90 shadow-[0_25px_60px_-15px_rgba(0,0,0,0.8)] ring-1 ring-white/10">
              {/* Browser / App Header */}
              <div className="flex items-center justify-between border-b border-zinc-800/80 bg-zinc-900/60 px-4 py-3 sm:px-6">
                <div className="flex items-center gap-2">
                  <span className="size-3 rounded-full bg-red-500/80" />
                  <span className="size-3 rounded-full bg-yellow-500/80" />
                  <span className="size-3 rounded-full bg-emerald-500/80" />
                  <span className="ml-3 font-mono text-xs text-zinc-400">
                    Deskwise Workspace · Interactive Preview
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={togglePlay}
                    aria-label={isPlaying ? 'Pause video' : 'Play video'}
                    className="grid size-7 place-items-center rounded-md border border-zinc-700 bg-zinc-800/80 text-zinc-300 transition hover:bg-zinc-700 hover:text-white"
                  >
                    {isPlaying ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
                  </button>
                  <button
                    type="button"
                    onClick={handleFullscreen}
                    aria-label="Fullscreen video"
                    className="grid size-7 place-items-center rounded-md border border-zinc-700 bg-zinc-800/80 text-zinc-300 transition hover:bg-zinc-700 hover:text-white"
                  >
                    <Maximize2 className="size-3.5" />
                  </button>
                </div>
              </div>

              {/* Video Element */}
              <div className="relative aspect-video w-full overflow-hidden bg-black">
                <video
                  ref={videoRef}
                  src="/feature-scroll.mp4"
                  autoPlay
                  loop
                  muted
                  playsInline
                  className="h-full w-full object-cover"
                />
              </div>

              {/* Bottom Status bar */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-zinc-800/80 bg-zinc-900/40 px-4 py-2.5 text-xs text-zinc-400 sm:px-6">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="size-3.5 text-[#ff5b24]" aria-hidden />
                  <span>Real-time document scrolling & citation verification</span>
                </div>
                <div className="flex items-center gap-4">
                  <span className="inline-flex items-center gap-1.5 text-zinc-300">
                    <ShieldCheck className="size-3.5 text-emerald-400" /> 100% Private & Audited
                  </span>
                </div>
              </div>
            </div>
          </div>
        </Reveal>

        {/* 3 Numbered Feature Blocks */}
        <div className="mt-16 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((item, index) => {
            const Icon = item.icon
            return (
              <Reveal key={item.num} delay={index * 100}>
                <div className="group relative flex h-full flex-col justify-between rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-7 transition-all duration-300 hover:border-[#ff5b24]/40 hover:bg-zinc-900/80">
                  <div>
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-3xl font-bold tracking-tight text-[#ff5b24]">
                        {item.num}
                      </span>
                      <span className="rounded-full border border-zinc-700 bg-zinc-800/60 px-2.5 py-1 text-[11px] font-medium text-zinc-300">
                        {item.badge}
                      </span>
                    </div>

                    <h3 className="mt-5 text-lg font-semibold tracking-tight text-white group-hover:text-[#ff7747]">
                      {item.title}
                    </h3>
                    <p className="mt-2.5 text-sm leading-relaxed text-zinc-400">
                      {item.description}
                    </p>
                  </div>

                  <div className="mt-6 flex items-center gap-2 border-t border-zinc-800/80 pt-4 text-xs font-medium text-zinc-400 group-hover:text-white">
                    <Icon className="size-4 text-[#ff5b24]" />
                    <span>Included in all plans</span>
                  </div>
                </div>
              </Reveal>
            )
          })}
        </div>

        {/* CTA Strip */}
        <div className="mt-12 text-center">
          <Link
            href="/enterprise?tab=create"
            className="inline-flex items-center gap-2 rounded-xl bg-[#ff5b24] px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-[#ff5b24]/20 transition-all hover:bg-[#e04815] hover:shadow-xl"
          >
            <span>Start your free company vault</span>
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </div>
      </div>
    </section>
  )
}
