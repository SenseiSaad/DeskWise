import Link from 'next/link'
import { ArrowRight, Check } from 'lucide-react'
import { HeroDemo } from './hero-demo'

export function Hero() {
  return (
    <section className="relative overflow-hidden pb-20 pt-10 sm:pt-14 lg:pb-24 lg:pt-20" aria-labelledby="hero-heading">
      <div aria-hidden className="hero-grid pointer-events-none absolute inset-0 -z-10" />
      <div
        aria-hidden
        className="pointer-events-none absolute -right-40 top-0 -z-10 size-[36rem] rounded-full bg-[radial-gradient(circle,rgba(217,167,95,0.16),transparent_65%)] blur-3xl"
      />

      <div className="container-page">
        <div className="grid items-center gap-16 lg:grid-cols-[1.05fr_0.95fr] lg:gap-12 xl:gap-20">
          <div className="max-w-[42rem]">
            <p className="animate-fade-up eyebrow" style={{ animationDelay: '80ms' }}>
              AI Assistant for Your Company Documents
            </p>

            <h1
              id="hero-heading"
              className="display-xl mt-5 animate-fade-up"
              style={{ animationDelay: '160ms' }}
            >
              Your company knowledge.
              <br />
              <span className="serif text-accent">Answered in seconds.</span>
            </h1>

            <p
              className="mt-6 max-w-[34rem] animate-fade-up text-[1.05rem] leading-relaxed text-muted-foreground sm:text-lg"
              style={{ animationDelay: '260ms' }}
            >
              Deskwise turns your company policies, contracts, and handbooks into a friendly, private AI assistant. Ask any question, get cited answers with exact page numbers, and generate ready-to-use HR forms instantly.
            </p>

            <div
              className="mt-8 flex animate-fade-up flex-col gap-3 sm:flex-row sm:items-center"
              style={{ animationDelay: '360ms' }}
            >
              <Link href="/enterprise?tab=create" className="btn btn-primary group">
                Start free trial
                <ArrowRight className="size-4 transition-transform duration-200 group-hover:translate-x-1" aria-hidden />
              </Link>
              <Link href="#features" className="btn btn-secondary">
                See interactive demo
              </Link>
            </div>

            <div
              className="mt-7 flex animate-fade-up flex-wrap items-center gap-x-5 gap-y-2 text-[12px] text-muted-foreground"
              style={{ animationDelay: '460ms' }}
            >
              {['No tech skills required', 'Zero data leaks', 'Exact page citations'].map((item) => (
                <span key={item} className="inline-flex items-center gap-1.5">
                  <Check className="size-3.5 text-accent" aria-hidden /> {item}
                </span>
              ))}
            </div>
          </div>

          <div className="animate-fade-up" style={{ animationDelay: '400ms' }}>
            <HeroDemo />
          </div>
        </div>
      </div>
    </section>
  )
}

export default Hero
