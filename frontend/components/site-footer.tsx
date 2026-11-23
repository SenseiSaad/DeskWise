import Link from 'next/link'
import { ShieldCheck } from 'lucide-react'
import { Logo } from './logo'
import { ThemeToggle } from './theme-toggle'

// Set NEXT_PUBLIC_RELEASE_STAGE=ga in Vercel/env to hide the beta badge without code changes.
const IS_BETA = (process.env.NEXT_PUBLIC_RELEASE_STAGE ?? 'beta').toLowerCase() !== 'ga'

const COLUMNS: { title: string; links: { href: string; label: string }[] }[] = [
  {
    title: 'Platform',
    links: [
      { href: '/#system', label: 'How it works' },
      { href: '/#security', label: 'Security model' },
      { href: '/infrastructure', label: 'Deployment architecture' },
      { href: '/pricing', label: 'Pricing' },
      { href: '/help', label: 'Getting started' },
    ],
  },
  {
    title: 'Company',
    links: [
      { href: '/about', label: 'About Deskwise' },
      { href: '/policy', label: 'Privacy & security' },
      { href: '/terms', label: 'Terms of service' },
      { href: 'mailto:saad@saadops.site', label: 'Contact us' },
    ],
  },
  {
    title: 'Access',
    links: [
      { href: '/enterprise?role=employee', label: 'Sign in' },
      { href: '/enterprise?tab=create', label: 'Create an organization' },
      { href: '/workspace', label: 'Workspace' },
    ],
  },
]

export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface/60">
      <div className="container-page">
        <div className="grid gap-12 py-14 sm:grid-cols-2 lg:grid-cols-[1.35fr_repeat(3,1fr)] lg:gap-8 lg:py-16">
          <div className="max-w-sm">
            <Logo />
            <p className="mt-5 text-sm leading-relaxed text-muted-foreground">
              Permission-aware knowledge infrastructure for organizations that need useful access —
              not open exposure.
            </p>
            <div className="mt-6 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1">
                <ShieldCheck className="size-3 text-accent" aria-hidden /> Tenant-isolated
              </span>
              <span className="rounded-full border border-border px-2.5 py-1">USD pricing</span>
              <span className="rounded-full border border-border px-2.5 py-1">Local AI ready</span>
              {IS_BETA && (
                <span className="inline-flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 font-medium text-accent">
                  <span className="size-1.5 rounded-full bg-accent" aria-hidden /> Public Beta · Iterating
                </span>
              )}
            </div>
          </div>

          {COLUMNS.map((column) => (
            <div key={column.title}>
              <p className="mb-5 text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                {column.title}
              </p>
              <ul className="flex flex-col gap-3.5">
                {column.links.map((link) => (
                  <li key={link.label}>
                    <Link
                      href={link.href}
                      className="text-sm text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="flex flex-col gap-5 border-t border-border py-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex flex-col gap-1 text-xs text-muted-foreground">
            <span>© 2026 Deskwise. Private by default.</span>
            <span>Enterprise knowledge infrastructure.</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-xs text-muted-foreground sm:inline">Appearance</span>
            <ThemeToggle variant="segmented" />
          </div>
        </div>
      </div>
    </footer>
  )
}

export default SiteFooter
