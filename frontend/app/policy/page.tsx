import Link from 'next/link'
import type { Metadata } from 'next'
import { ArrowRight, LockKeyhole, ShieldCheck } from 'lucide-react'
import { SiteHeader } from '@/components/site-header'
import { SiteFooter } from '@/components/site-footer'
import { Reveal } from '@/components/reveal'

export const metadata: Metadata = {
  title: 'Privacy & security',
  description:
    'How Deskwise protects company knowledge: tenant isolation, least privilege, permission-aware AI, and a complete audit trail.',
}

const POLICIES = [
  {
    title: 'Information we collect',
    body: 'We collect your work email address, full name (if provided), organization name, role/department assignment, uploaded company documents, AI chat queries, and security audit events required to operate your workspace.',
  },
  {
    title: 'Google Sign-In & OAuth data',
    body: 'When you use "Continue with Google", we verify your Google ID token and receive only your basic profile (email address, email verification status, and display name) to authenticate your Deskwise account. We never access your Gmail, Google Drive, or contacts, and never sell or share Google user data with third parties for advertising.',
  },
  {
    title: 'Private by default & tenant isolation',
    body: 'Every document, indexed chunk, member, and audit event is scoped to its owning company. Deskwise enforces pre-retrieval role, department, and clearance checks so users only receive answers from documents they are authorized to read.',
  },
  {
    title: 'AI processing & PII redaction',
    body: 'When a user asks a question, only the permitted document excerpts and prompt are sent to the configured AI provider (or processed locally via Ollama/self-hosted models) to generate a cited answer. Optional PII redaction masks sensitive patterns before external LLM calls.',
  },
  {
    title: 'Cookies & session security',
    body: 'Deskwise uses strictly necessary HttpOnly, secure session cookies (access and rotating refresh tokens) to keep you signed in and protect against XSS. We do not use third-party advertising trackers.',
  },
  {
    title: 'Audit trail, retention & deletion',
    body: 'Sign-ins, uploads, downloads, permission changes, break-glass events, and AI queries are recorded in your organization’s tamper-evident, append-only audit log. Workspace administrators can delete documents (unless under legal hold) or request full workspace deletion by contacting support.',
  },
]

const SERVICES = [
  {
    name: 'Vercel',
    role: 'Web & API hosting',
    location: 'Global edge / United States',
    detail:
      'Serves the Next.js web application and serverless API endpoints over TLS.',
  },
  {
    name: 'Managed PostgreSQL & Object Storage',
    role: 'Database & encrypted document chunks',
    location: 'United States / Regional cloud',
    detail:
      'Stores tenant-isolated relational data, encrypted document chunks, vector embeddings, and uploaded files.',
  },
  {
    name: 'Configured AI Provider (Gemini / OpenAI / Ollama)',
    role: 'AI inference',
    location: 'Per workspace configuration',
    detail:
      'Receives only the question and the passages the asking user is permitted to see to generate cited answers.',
  },
  {
    name: 'Google Identity Services & Transactional SMTP',
    role: 'Authentication & email delivery',
    location: 'Global',
    detail:
      'Verifies Google Sign-In tokens and delivers account verification, invitation, and password-reset emails.',
  },
]

const slug = (value: string) =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '')

export default function PolicyPage() {
  return (
    <main id="main-content" className="min-h-screen overflow-x-clip">
      <SiteHeader />

      <section className="relative overflow-hidden pb-14 pt-12 sm:pt-16 lg:pb-20 lg:pt-20" aria-labelledby="policy-title">
        <div aria-hidden className="hero-grid pointer-events-none absolute inset-0 -z-10" />
        <div className="container-page">
          <div className="max-w-3xl">
            <p className="animate-fade-up eyebrow" style={{ animationDelay: '80ms' }}>
              Privacy & security
            </p>
            <h1
              id="policy-title"
              className="display-xl mt-5 animate-fade-up"
              style={{ animationDelay: '160ms' }}
            >
              The rules behind a <span className="serif text-accent">private vault.</span>
            </h1>
            <p
              className="mt-6 max-w-2xl animate-fade-up text-[1.02rem] leading-relaxed text-muted-foreground sm:text-lg"
              style={{ animationDelay: '260ms' }}
            >
              Deskwise is designed around employer-controlled access. These principles describe the
              product behavior that protects company knowledge.
            </p>
            <p
              className="mt-4 animate-fade-up font-mono text-[9.5px] uppercase tracking-[0.12em] text-muted-foreground"
              style={{ animationDelay: '320ms' }}
            >
              Product behavior · October 2026
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
                  <ShieldCheck className="size-3.5 text-accent" aria-hidden /> On this page
                </p>
                <nav aria-label="Security sections" className="mt-4 flex flex-col gap-2.5">
                  {POLICIES.map((policy, index) => (
                    <a
                      key={policy.title}
                      href={`#${slug(policy.title)}`}
                      className="group flex items-baseline gap-2 text-[11.5px] text-muted-foreground transition-colors hover:text-foreground"
                    >
                      <span className="font-mono text-[8.5px] text-accent">
                        {String(index + 1).padStart(2, '0')}
                      </span>
                      {policy.title}
                    </a>
                  ))}
                </nav>
              </div>
              <div className="mt-4 flex items-start gap-2.5 rounded-xl border border-border p-4">
                <LockKeyhole className="mt-0.5 size-3.5 shrink-0 text-accent" aria-hidden />
                <p className="text-[10.5px] leading-relaxed text-muted-foreground">
                  No public browsing, no shared crawl, no cross-tenant retrieval. The company owns
                  the workspace and the permissions inside it.
                </p>
              </div>
            </aside>
          </Reveal>

          <div>
            {POLICIES.map((policy, index) => (
              <Reveal key={policy.title} delay={index * 45}>
                <article
                  id={slug(policy.title)}
                  className="scroll-mt-28 border-t border-border py-7 sm:py-8"
                >
                  <div className="grid gap-3 sm:grid-cols-[3rem_1fr] sm:gap-6">
                    <span className="font-mono text-[10px] text-accent">
                      {String(index + 1).padStart(2, '0')}
                    </span>
                    <div>
                      <h2 className="text-[1.15rem] font-medium tracking-[-0.025em]">{policy.title}</h2>
                      <p className="mt-2.5 max-w-2xl text-[13px] leading-[1.75] text-muted-foreground">
                        {policy.body}
                      </p>
                    </div>
                  </div>
                </article>
              </Reveal>
            ))}

            <Reveal>
              <p className="mt-6 border-t border-border pt-5 text-[10.5px] leading-relaxed text-muted-foreground">
                This page documents the implemented access model. Production deployments should add
                environment-specific retention, encryption, backup, incident-response, and legal
                review.
              </p>
            </Reveal>
          </div>
        </div>
      </section>

      <section
        className="container-page scroll-mt-28 pb-16 sm:pb-20"
        aria-labelledby="services-title"
      >
        <Reveal>
          <div className="border-t border-border pt-10 sm:pt-12">
            <div className="max-w-2xl">
              <p className="eyebrow">Current deployment</p>
              <h2 id="services-title" className="display-md mt-4">
                Services that can touch data.
              </h2>
              <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
                Deskwise is in private beta. These are the third-party services in the current
                deployment, what each receives, and where it runs.
              </p>
            </div>

            <div className="mt-9 divide-y divide-border border-y border-border">
              {SERVICES.map((service) => (
                <div
                  key={service.name}
                  className="grid gap-2 py-5 sm:grid-cols-[0.85fr_0.55fr_1.6fr] sm:gap-6"
                >
                  <div>
                    <p className="text-[13px] font-medium">{service.name}</p>
                    <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.13em] text-accent">
                      {service.role}
                    </p>
                  </div>
                  <p className="text-[11px] leading-relaxed text-muted-foreground">
                    {service.location}
                  </p>
                  <p className="text-[12px] leading-relaxed text-muted-foreground">
                    {service.detail}
                  </p>
                </div>
              ))}
            </div>

            <div className="mt-6 flex items-start gap-3 rounded-xl border border-border bg-surface/60 p-5">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
              <p className="max-w-3xl text-[11.5px] leading-relaxed text-muted-foreground">
                <span className="font-medium text-foreground">Production target.</span> The backend
                and data layer are being prepared on AWS: ECS/Fargate, RDS, S3, Route 53 and
                CloudWatch, alongside Amplify and Bedrock. Until that cutover is complete, the beta
                services above remain in use. We will update this page before production onboarding.
              </p>
            </div>
          </div>
        </Reveal>
      </section>

      <section className="container-page pb-16 sm:pb-20">
        <Reveal>
          <div className="flex flex-col gap-6 rounded-xl border border-border bg-surface/70 p-7 sm:flex-row sm:items-center sm:justify-between sm:p-9">
            <div>
              <p className="eyebrow">Questions</p>
              <h2 className="display-md mt-3">Want the long version?</h2>
            </div>
            <div className="flex flex-col gap-2.5 sm:flex-row">
              <Link href="/help" className="btn btn-primary">
                Read the field guide <ArrowRight className="size-4" aria-hidden />
              </Link>
              <a href="mailto:hello@deskwise.site" className="btn btn-secondary">
                Contact us
              </a>
            </div>
          </div>
        </Reveal>
      </section>

      <SiteFooter />
    </main>
  )
}
