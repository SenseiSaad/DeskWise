'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { ArrowRight, Check, Sparkles } from 'lucide-react'
import { ChatMockup } from './mockups'

// Set NEXT_PUBLIC_RELEASE_STAGE=ga in Vercel/env to hide the beta badge without code changes.
const IS_BETA = (process.env.NEXT_PUBLIC_RELEASE_STAGE ?? 'beta').toLowerCase() !== 'ga'

export function Hero() {
  const [step, setStep] = useState(3)
  const [isVisible, setIsVisible] = useState(false)

  useEffect(() => {
    setIsVisible(true)
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    let cancelled = false
    const timers: ReturnType<typeof setTimeout>[] = []
    const run = () => {
      setStep(0)
      ;[1, 2, 3].forEach((s, i) => timers.push(setTimeout(() => !cancelled && setStep(s), 600 + i * 1400)))
      timers.push(setTimeout(() => !cancelled && run(), 9000))
    }
    run()
    return () => {
      cancelled = true
      timers.forEach(clearTimeout)
    }
  }, [])

  return (
    <section className="relative overflow-hidden pb-24 pt-16 sm:pt-20 lg:pb-32 lg:pt-28" aria-labelledby="hero-heading">
      {/* Animated background gradients */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div 
          className="absolute -left-1/4 top-0 h-96 w-96 rounded-full bg-accent/10 blur-3xl glow-pulse"
          style={{ animationDelay: '0s' }}
        />
        <div 
          className="absolute -right-1/4 top-1/3 h-96 w-96 rounded-full bg-accent/8 blur-3xl glow-pulse"
          style={{ animationDelay: '1.5s' }}
        />
      </div>

      <div className="container-page relative">
        <div className="grid items-center gap-16 lg:grid-cols-2 lg:gap-20">
          <div className="max-w-2xl">
            <div className={`flex flex-wrap items-center gap-2.5 transition-all duration-700 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}>
              <div className="eyebrow">
                <Sparkles className="size-3.5" aria-hidden />
                AI assistant for your company documents
              </div>
              {IS_BETA && (
                <span
                  role="status"
                  title="Deskwise is in final beta testing and actively iterating based on early feedback."
                  className="inline-flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent/10 px-3 py-1 text-xs font-medium text-accent"
                >
                  <span className="size-1.5 rounded-full bg-accent" aria-hidden />
                  Public Beta · Final testing
                </span>
              )}
            </div>
            
            <h1 
              id="hero-heading" 
              className={`display-xl mt-6 transition-all duration-700 delay-100 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}
            >
              Your company knowledge.
              <br />
              <span className="serif text-accent bg-gradient-to-r from-accent to-accent/80 bg-clip-text text-transparent">
                Answered in seconds.
              </span>
            </h1>
            
            <p
              className={`mt-7 text-lg leading-relaxed text-muted-foreground transition-all duration-700 delay-200 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}
            >
              Upload your policies and contracts. Ask a question, get the answer with the page it came from, and
              download ready-to-send forms and letters.
            </p>
            
            <div 
              className={`mt-10 flex flex-col gap-4 sm:flex-row transition-all duration-700 delay-300 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}
            >
              <Link href="/enterprise?tab=create" className="btn btn-accent btn-lg group hover-glow">
                Start free
                <ArrowRight className="size-4 transition-all group-hover:translate-x-1.5" aria-hidden />
              </Link>
              <Link href="#story" className="btn btn-secondary btn-lg">
                See how it works
              </Link>
            </div>
            
            <ul 
              className={`mt-8 flex flex-wrap gap-x-7 gap-y-3 text-sm text-muted-foreground transition-all duration-700 delay-[400ms] ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}
            >
              {['No technical skills needed', 'No card to start', 'Your data stays private'].map((t, i) => (
                <li 
                  key={t} 
                  className="inline-flex items-center gap-2 transition-all hover:text-foreground"
                  style={{ transitionDelay: `${400 + i * 50}ms` }}
                >
                  <span className="flex size-5 items-center justify-center rounded-full bg-accent/10">
                    <Check className="size-3 text-accent" aria-hidden />
                  </span>
                  {t}
                </li>
              ))}
            </ul>
          </div>

          <div 
            className={`transition-all duration-700 delay-300 ${isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-8'}`}
          >
            <div className="group relative">
              {/* Glow effect */}
              <div className="absolute -inset-1 rounded-[2rem] bg-gradient-to-r from-accent/20 via-accent/10 to-accent/20 opacity-0 blur-xl transition-opacity duration-500 group-hover:opacity-100" />
              
              {/* Main card */}
              <div className="card-hover relative overflow-hidden rounded-[1.75rem] border border-border bg-surface/80 p-5 shadow-2xl backdrop-blur-sm sm:p-7">
                <div className="mb-5 flex items-center justify-between border-b border-border pb-4">
                  <div className="flex items-center gap-2.5 text-sm font-medium">
                    <span className="flex size-3 items-center justify-center">
                      <span className="absolute size-3 animate-ping rounded-full bg-accent/50" />
                      <span className="relative size-2 rounded-full bg-accent" />
                    </span>
                    Ask Deskwise
                  </div>
                  <div className="flex gap-1.5">
                    <span className="size-2.5 rounded-full bg-border-strong" />
                    <span className="size-2.5 rounded-full bg-border-strong" />
                    <span className="size-2.5 rounded-full bg-border-strong" />
                  </div>
                </div>
                
                <div className="min-h-[20rem] rounded-xl bg-background/50 p-1">
                  <ChatMockup step={step} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

export default Hero
