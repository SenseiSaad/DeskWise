import Link from 'next/link'
import { Check, Minus } from 'lucide-react'
import { Reveal } from '@/components/reveal'
import { FALLBACK_PLANS, PLAN_COPY, formatUSD, storageLabel } from '@/lib/pricing'
import type { Plan } from '@/lib/api'

type P = Omit<Plan, 'id'>

const num = (n: number | null, unit: string) => (n == null ? `Unlimited ${unit}` : `${n.toLocaleString('en-US')} ${unit}`)

function featuresOf(p: P): string[] {
  const list = [
    num(p.max_members, 'team members'),
    num(p.max_documents, 'documents'),
    storageLabel(p.storage_mb),
    `${p.monthly_ask_limit?.toLocaleString('en-US') ?? 'Unlimited'} AI questions / month`,
    'Ready-to-send forms & letters',
  ]
  if (p.allow_versions) list.push('Document version history')
  if (p.allow_departments) list.push('Department permissions')
  if (p.allow_custom_llm) list.push('Bring your own AI key')
  return list
}

const TABLE: { label: string; value: (p: P) => string | boolean }[] = [
  { label: 'Price per month', value: (p) => (p.price_usd === 0 ? 'Free' : formatUSD(p.price_usd)) },
  { label: 'Team members', value: (p) => num(p.max_members, '').trim() || 'Unlimited' },
  { label: 'Documents', value: (p) => (p.max_documents == null ? 'Unlimited' : p.max_documents.toLocaleString('en-US')) },
  { label: 'Storage', value: (p) => storageLabel(p.storage_mb).replace(' storage', '') },
  { label: 'AI questions / month', value: (p) => p.monthly_ask_limit?.toLocaleString('en-US') ?? 'Unlimited' },
  { label: 'Forms & letters generator', value: () => true },
  { label: 'Page-level citations', value: () => true },
  { label: 'Audit log', value: () => true },
  { label: 'Document version history', value: (p) => p.allow_versions },
  { label: 'Department permissions', value: (p) => p.allow_departments },
  { label: 'Bring your own AI key', value: (p) => p.allow_custom_llm },
]

function Cell({ v }: { v: string | boolean }) {
  if (typeof v === 'string') return <span className="font-medium">{v}</span>
  return v ? (
    <span className="inline-grid size-5 place-items-center rounded-full bg-accent-soft text-accent">
      <Check className="size-3 stroke-[3]" aria-label="Included" />
    </span>
  ) : (
    <Minus className="mx-auto size-4 text-muted-foreground/60" aria-label="Not included" />
  )
}

export function PricingSection({ showTable = true }: { showTable?: boolean }) {
  const plans = FALLBACK_PLANS
  return (
    <section id="pricing" className="scroll-mt-20 py-20 sm:py-28" aria-labelledby="pricing-title">
      <div className="container-page">
        <div className="mx-auto max-w-2xl text-center">
          <p className="eyebrow justify-center">Pricing</p>
          <h2 id="pricing-title" className="display-lg mt-5">
            Simple plans. Start free.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-muted-foreground">
            Pay only when your team grows. Change or cancel any time. Cards from any country are accepted.
          </p>
        </div>

        <div className="mt-14 grid gap-5 sm:grid-cols-2 xl:grid-cols-4">
          {plans.map((p, i) => {
            const copy = PLAN_COPY[p.name]
            const hot = copy?.highlight
            return (
              <Reveal key={p.name} delay={i * 70}>
                <div
                  className={`relative flex h-full flex-col rounded-2xl border bg-surface p-6 ${
                    hot ? 'border-accent ring-1 ring-accent' : 'border-border'
                  }`}
                >
                  {hot && (
                    <span className="absolute right-5 top-5 rounded-full bg-accent px-2.5 py-0.5 text-xs font-semibold text-accent-foreground">
                      Most popular
                    </span>
                  )}
                  <h3 className="text-lg font-semibold">{p.name}</h3>
                  <p className="mt-1 text-sm text-muted-foreground">{copy?.tagline}</p>
                  <p className="mt-5 flex items-baseline gap-1">
                    <span className="text-4xl font-bold tracking-tight">{formatUSD(p.price_usd)}</span>
                    <span className="text-sm text-muted-foreground">/month</span>
                  </p>
                  <Link
                    href="/enterprise?tab=create"
                    className={`btn mt-5 w-full ${hot ? 'btn-accent' : 'btn-secondary'}`}
                  >
                    {p.price_usd === 0 ? 'Start free' : `Choose ${p.name}`}
                  </Link>
                  <ul className="mt-6 space-y-3 border-t border-border pt-5 text-sm">
                    {featuresOf(p).map((f) => (
                      <li key={f} className="flex items-start gap-2.5">
                        <Check className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                        <span>{f}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </Reveal>
            )
          })}
        </div>

        {showTable && (
          <div className="mt-20">
            <h3 className="text-center text-2xl font-semibold tracking-tight sm:text-3xl">Compare plans</h3>
            <div className="mt-8 overflow-x-auto rounded-2xl border border-border">
              <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
                <thead>
                  <tr className="bg-accent text-accent-foreground">
                    <th scope="col" className="px-5 py-4 font-semibold">What you get</th>
                    {plans.map((p) => (
                      <th key={p.name} scope="col" className="px-4 py-4 text-center font-semibold">{p.name}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border bg-surface">
                  {TABLE.map((row) => (
                    <tr key={row.label}>
                      <th scope="row" className="px-5 py-3.5 font-medium">{row.label}</th>
                      {plans.map((p) => (
                        <td key={p.name} className="px-4 py-3.5 text-center">
                          <Cell v={row.value(p)} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-6 text-center text-sm text-muted-foreground">
              Need something custom?{' '}
              <a
                href="mailto:hello@openvault.site?subject=Deskwise%20custom%20plan"
                className="font-medium text-accent underline underline-offset-4"
              >
                Talk to us
              </a>
            </p>
          </div>
        )}
      </div>
    </section>
  )
}

export default PricingSection
