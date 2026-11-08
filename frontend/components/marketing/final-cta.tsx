import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import { Reveal } from '@/components/reveal'

export function FinalCta() {
  return (
    <section className="py-20 sm:py-28" aria-labelledby="cta-heading">
      <div className="container-page">
        <Reveal>
          <div className="rounded-3xl border border-border bg-surface px-6 py-14 text-center sm:px-12">
            <h2 id="cta-heading" className="display-lg mx-auto max-w-2xl">
              Give your team answers, <span className="serif text-accent">not searches.</span>
            </h2>
            <p className="mx-auto mt-4 max-w-md text-base text-muted-foreground">
              Start free. Upload your first document in minutes.
            </p>
            <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row">
              <Link href="/enterprise?tab=create" className="btn btn-primary">
                Start free <ArrowRight className="size-4" aria-hidden />
              </Link>
              <Link href="/enterprise?role=employee" className="btn btn-secondary">
                Sign in
              </Link>
            </div>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

export default FinalCta
