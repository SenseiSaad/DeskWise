import Link from 'next/link'
import type { Metadata } from 'next'
import { ArrowRight, Scale, ShieldCheck } from 'lucide-react'
import { SiteHeader } from '@/components/site-header'
import { SiteFooter } from '@/components/site-footer'
import { Reveal } from '@/components/reveal'

export const metadata: Metadata = {
  title: 'Terms of Service',
  description:
    'Terms of Service governing use of the Deskwise multi-tenant company knowledge base and AI assistant.',
}

const TERMS = [
  {
    title: '1. Acceptance & beta status',
    body: 'By creating an organization or signing in to Deskwise, you agree to these Terms of Service and our Privacy Policy. Deskwise is currently offered in public beta; features and limits may evolve as we iterate with early customers.',
  },
  {
    title: '2. Workspace ownership & admin responsibility',
    body: 'The organization that creates a Deskwise workspace owns the documents uploaded to it. Company administrators are responsible for inviting authorized team members, assigning accurate roles, departments, and clearance levels, and revoking access when a member leaves.',
  },
  {
    title: '3. Account security',
    body: 'You must provide an accurate work email address and keep your credentials confidential. Accounts are specific to one individual and may not be shared. Notify us immediately if you suspect unauthorized access.',
  },
  {
    title: '4. Acceptable use',
    body: 'You may not use Deskwise to store or distribute unlawful content, malware, or material that infringes third-party intellectual property, nor attempt to probe, bypass, or disrupt tenant isolation, rate limits, or authentication controls.',
  },
  {
    title: '5. AI answers & generated documents',
    body: 'Deskwise generates answers and draft forms from the documents your organization uploads. While answers include source citations, AI outputs can contain errors and do not constitute legal, financial, medical, or compliance advice. Always verify critical information against the cited source document.',
  },
  {
    title: '6. Plans, billing & termination',
    body: 'Paid subscription tiers are billed in advance on a monthly or annual cycle as shown on the pricing page. You may cancel or export your documents at any time. We may suspend accounts that violate these Terms or pose a security risk.',
  },
  {
    title: '7. Limitation of liability & warranty disclaimer',
    body: 'Deskwise is provided "as is" without warranties of uninterrupted availability. To the maximum extent permitted by law, Deskwise is not liable for indirect, incidental, or consequential damages arising from use of the service.',
  },
]

export default function TermsPage() {
  return (
    <main id="main-content" className="min-h-screen overflow-x-clip">
      <SiteHeader />

      <section className="relative overflow-hidden pb-14 pt-12 sm:pt-16 lg:pb-20 lg:pt-20" aria-labelledby="terms-title">
        <div aria-hidden className="hero-grid pointer-events-none absolute inset-0 -z-10" />
        <div className="container-page">
          <div className="max-w-3xl">
            <p className="animate-fade-up eyebrow" style={{ animationDelay: '80ms' }}>
              Terms of Service
            </p>
            <h1
              id="terms-title"
              className="display-xl mt-5 animate-fade-up"
              style={{ animationDelay: '160ms' }}
            >
              Clear terms for <span className="serif text-accent">company knowledge.</span>
            </h1>
            <p
              className="mt-6 max-w-2xl animate-fade-up text-[1.02rem] leading-relaxed text-muted-foreground sm:text-lg"
              style={{ animationDelay: '260ms' }}
            >
              Plain-English terms governing your organization&apos;s workspace, data ownership, and
              acceptable use on Deskwise.
            </p>
            <p
              className="mt-4 animate-fade-up font-mono text-[9.5px] uppercase tracking-[0.12em] text-muted-foreground"
              style={{ animationDelay: '320ms' }}
            >
              Last updated · November 2026
            </p>
          </div>
        </div>
      </section>

      <section className="container-page pb-16 sm:pb-20">
        <div className="grid gap-12 lg:grid-cols-[0.6fr_1.4fr] lg:gap-16">
          <Reveal>
            <aside className="lg:sticky lg:top-28">
              <div className="rounded-xl border border-border bg-surface/70 p-5">
                <p className="flex items-center gap-2 text-[11px] font-medium">
                  <Scale className="size-3.5 text-accent" aria-hidden /> Key points
                </p>
                <p className="mt-3 text-[11.5px] leading-relaxed text-muted-foreground">
                  Your organization owns its uploaded documents. Admins control who has access, and
                  Deskwise enforces those permissions before retrieval.
                </p>
                <div className="mt-4 border-t border-border pt-3">
                  <Link
                    href="/policy"
                    className="inline-flex items-center gap-1.5 text-xs font-medium text-accent hover:underline"
                  >
                    <ShieldCheck className="size-3.5" aria-hidden /> Read Privacy &amp; Security Policy
                  </Link>
                </div>
              </div>
            </aside>
          </Reveal>

          <div>
            {TERMS.map((item, index) => (
              <Reveal key={item.title} delay={index * 40}>
                <article className="border-t border-border py-7 sm:py-8">
                  <h2 className="text-[1.15rem] font-medium tracking-[-0.025em]">{item.title}</h2>
                  <p className="mt-2.5 max-w-2xl text-[13px] leading-[1.75] text-muted-foreground">
                    {item.body}
                  </p>
                </article>
              </Reveal>
            ))}

            <Reveal>
              <div className="mt-8 flex flex-col gap-4 rounded-xl border border-border bg-surface/70 p-6 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm font-medium text-foreground">Questions about these terms?</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Reach us anytime at saad@saadops.site.
                  </p>
                </div>
                <Link href="/enterprise" className="btn btn-primary">
                  Go to workspace sign in <ArrowRight className="size-4" aria-hidden />
                </Link>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      <SiteFooter />
    </main>
  )
}
