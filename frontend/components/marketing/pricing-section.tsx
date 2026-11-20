'use client'

import { useState } from 'react'
import Link from 'next/link'
import { motion, AnimatePresence } from 'motion/react'
import { Check, ChevronDown, Minus } from 'lucide-react'
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

export function PricingSection({ showTable = false }: { showTable?: boolean }) {
  const [tableOpen, setTableOpen] = useState(showTable)
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
              <Reveal key={p.name} delay={i * 70} className="h-full">
                <div
                  className={`group relative flex h-full flex-col rounded-2xl border bg-surface p-6 transition-all duration-300 hover:-translate-y-1 hover:shadow-xl hover:shadow-black/5 ${
                    hot ? 'border-accent ring-1 ring-accent' : 'border-border hover:border-border-strong'
                  }`}
                >
                  {hot && (
                    <span className="absolute right-5 top-5 rounded-full bg-accent px-2.5 py-0.5 text-xs font-semibold text-accent-foreground shadow-sm">
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
                    className={`btn mt-5 w-full transition-all duration-200 ${hot ? 'btn-accent hover-glow' : 'btn-secondary'}`}
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

        {/* Buttery smooth comparison table toggle */}
        <div className="mt-12 text-center">
          <button
            type="button"
            onClick={() => setTableOpen((prev) => !prev)}
            aria-expanded={tableOpen}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-5 py-2.5 text-sm font-medium text-foreground transition-all duration-200 hover:border-border-strong hover:bg-surface-2"
          >
            <span>{tableOpen ? 'Hide feature comparison' : 'Compare all plan features'}</span>
            <motion.span
              animate={{ rotate: tableOpen ? 180 : 0 }}
              transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
              className="grid place-items-center"
            >
              <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
            </motion.span>
          </button>
        </div>

        <AnimatePresence initial={false}>
          {tableOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
              className="overflow-hidden"
            >
              <div className="pt-10">
                <h3 className="text-center text-2xl font-semibold tracking-tight sm:text-3xl">See features included</h3>
                <div className="mt-8 overflow-x-auto rounded-2xl border border-border bg-surface shadow-sm">
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
                        <tr key={row.label} className="transition-colors hover:bg-surface-2/60">
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
                    href="mailto:hello@deskwise.site?subject=Deskwise%20custom%20plan"
                    className="font-medium text-accent underline underline-offset-4 hover:text-accent/80 transition-colors"
                  >
                    Talk to us
                  </a>
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </section>
  )
}

export default PricingSection
