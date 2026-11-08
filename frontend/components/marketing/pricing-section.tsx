'use client'

import Link from 'next/link'
import { Check, Minus, Sparkles, ArrowRight } from 'lucide-react'
import { Reveal } from '@/components/reveal'

interface PlanCardProps {
  name: string
  price: string
  period?: string
  description: string
  popular?: boolean
  features: string[]
  ctaText?: string
  ctaLink?: string
}

const PLANS: PlanCardProps[] = [
  {
    name: 'Starter Plan',
    price: '$50',
    period: '/month',
    description: 'Perfect for small teams, startups, and growing businesses.',
    features: [
      'Unlimited docs',
      '200+ templates',
      '100 GB file storage',
      'Basic Security',
    ],
    ctaText: 'Try it free',
    ctaLink: '/enterprise?tab=create',
  },
  {
    name: 'Professional Plan',
    price: '$80.00',
    period: '/month',
    popular: true,
    description: 'Perfect for growing businesses ready to scale their operations.',
    features: [
      'Unlimited docs',
      '1000+ templates',
      '600 GB file storage',
      'Enhanced security',
      'Department permissions',
      'AI Document Generator',
    ],
    ctaText: 'Try it free',
    ctaLink: '/enterprise?tab=create',
  },
  {
    name: 'Enterprise Plan',
    price: '$150',
    period: '/month',
    description: 'Comprehensive and scalable solutions for growing large organizations.',
    features: [
      'Unlimited docs',
      'Unlimited templates',
      '1 TB file storage',
      'Premium widgets',
      'Customisable dashboard',
      'Advanced security',
      'Priority support',
    ],
    ctaText: 'Try it free',
    ctaLink: '/enterprise?tab=create',
  },
]

type TableRow = {
  feature: string
  starter: boolean | string
  pro: boolean | string
  enterprise: boolean | string
}

const COMPARISON_ROWS: TableRow[] = [
  { feature: 'Price', starter: '$50/month', pro: '$80/month', enterprise: '$150/month' },
  { feature: 'Basic features at no cost', starter: true, pro: true, enterprise: true },
  { feature: 'Access to basic analytics', starter: true, pro: true, enterprise: true },
  { feature: 'Real-time data processing', starter: false, pro: true, enterprise: true },
  { feature: 'Customizable data reports', starter: false, pro: true, enterprise: true },
  { feature: 'Advanced data visualization tools', starter: false, pro: true, enterprise: true },
  { feature: 'Team collaboration tools', starter: false, pro: true, enterprise: true },
  { feature: 'Unlimited data storage', starter: '100 GB', pro: '600 GB', enterprise: 'Unlimited (1 TB)' },
  { feature: 'Predictive analytics & AI search', starter: false, pro: true, enterprise: true },
  { feature: 'API access for integrations', starter: false, pro: true, enterprise: true },
  { feature: 'Data export options (PDF, DOCX)', starter: true, pro: true, enterprise: true },
]

export function PricingSection({ showTable = true }: { showTable?: boolean }) {
  return (
    <section
      id="pricing"
      className="relative overflow-hidden bg-[#0a0a0c] py-20 text-white sm:py-28"
      aria-labelledby="pricing-title"
    >
      {/* Background glow effects */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-10 -z-10 h-[36rem] w-[50rem] -translate-x-1/2 rounded-full bg-[radial-gradient(ellipse_at_center,rgba(255,91,36,0.1),transparent_70%)] blur-3xl"
      />

      <div className="container-page">
        {/* Header */}
        <div className="mx-auto max-w-2xl text-center">
          <Reveal>
            <div className="inline-flex items-center gap-1.5 rounded-full border border-[#ff5b24]/30 bg-[#ff5b24]/10 px-3 py-1 text-xs font-semibold text-[#ff7747]">
              <Sparkles className="size-3.5" aria-hidden />
              <span>Pricing</span>
            </div>
            <h2
              id="pricing-title"
              className="mt-4 text-3xl font-semibold tracking-tight text-white sm:text-4xl lg:text-5xl"
            >
              Flexible Pricing Plans
            </h2>
            <p className="mt-4 text-base leading-relaxed text-zinc-400">
              Founded by data experts, we create cutting-edge SaaS analytics platforms tailored for businesses of all sizes.
            </p>
          </Reveal>
        </div>

        {/* 3 Pricing Cards */}
        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {PLANS.map((plan, index) => (
            <Reveal key={plan.name} delay={index * 90}>
              <div
                className={`relative flex h-full flex-col justify-between rounded-2xl border p-7 sm:p-8 transition-all duration-300 ${
                  plan.popular
                    ? 'border-[#ff5b24] bg-zinc-900/90 shadow-[0_0_35px_-8px_rgba(255,91,36,0.25)] ring-1 ring-[#ff5b24]/50'
                    : 'border-zinc-800/90 bg-zinc-900/40 hover:border-zinc-700 hover:bg-zinc-900/70'
                }`}
              >
                {/* Popular Badge */}
                {plan.popular && (
                  <div className="absolute right-6 top-6">
                    <span className="rounded-full bg-[#ff5b24]/20 border border-[#ff5b24]/40 px-2.5 py-0.5 text-[10px] font-semibold tracking-wider text-[#ff7747] uppercase">
                      Most Popular
                    </span>
                  </div>
                )}

                <div>
                  <h3 className="text-base font-semibold text-zinc-200">{plan.name}</h3>
                  <div className="mt-4 flex items-baseline gap-1">
                    <span className="text-4xl font-bold tracking-tight text-white">
                      {plan.price}
                    </span>
                    <span className="text-sm font-medium text-zinc-400">{plan.period}</span>
                  </div>
                  <p className="mt-3 text-xs leading-relaxed text-zinc-400">{plan.description}</p>

                  {/* CTA button */}
                  <div className="mt-6">
                    <Link
                      href={plan.ctaLink || '/enterprise?tab=create'}
                      className={`inline-flex w-full items-center justify-center rounded-xl py-2.5 text-xs font-semibold transition-all ${
                        plan.popular
                          ? 'bg-[#ff5b24] text-white shadow-md shadow-[#ff5b24]/25 hover:bg-[#e04815]'
                          : 'bg-[#ff5b24] text-white hover:bg-[#e04815]'
                      }`}
                    >
                      {plan.ctaText || 'Try it free'}
                    </Link>
                  </div>

                  {/* Features list */}
                  <div className="mt-8">
                    <p className="text-xs font-semibold text-zinc-300">Features:</p>
                    <ul className="mt-4 space-y-3">
                      {plan.features.map((feat) => (
                        <li key={feat} className="flex items-start gap-2.5 text-xs text-zinc-300">
                          <span className="grid size-4 shrink-0 place-items-center rounded-full bg-[#ff5b24]/20 text-[#ff5b24]">
                            <Check className="size-2.5 stroke-[3]" />
                          </span>
                          <span>{feat}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </Reveal>
          ))}
        </div>

        {/* Feature Comparison Table ("See Features Includes") */}
        {showTable && (
          <div className="mt-24">
            <Reveal>
              <div className="mx-auto max-w-2xl text-center">
                <span className="text-xs font-medium text-zinc-400">See features includes</span>
                <h3 className="mt-2 text-2xl font-bold tracking-tight text-white sm:text-3xl">
                  See Features Includes
                </h3>
              </div>
            </Reveal>

            <Reveal delay={100}>
              <div className="mt-8 overflow-hidden rounded-2xl border border-zinc-800 shadow-2xl">
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-left text-xs sm:text-sm">
                    {/* Header Row */}
                    <thead>
                      <tr className="bg-[#ff5b24] text-white font-semibold">
                        <th className="py-3.5 pl-6 pr-4 sm:py-4">Plan Overview</th>
                        <th className="px-4 py-3.5 text-center sm:py-4">Starter Plan</th>
                        <th className="px-4 py-3.5 text-center sm:py-4">Professional Plan</th>
                        <th className="py-3.5 pl-4 pr-6 text-center sm:py-4">Enterprise Plan</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/80 bg-zinc-950/80 text-zinc-300">
                      {COMPARISON_ROWS.map((row) => (
                        <tr
                          key={row.feature}
                          className="transition-colors hover:bg-zinc-900/60"
                        >
                          <td className="py-3.5 pl-6 pr-4 font-medium text-zinc-200">
                            {row.feature}
                          </td>
                          <td className="px-4 py-3.5 text-center text-zinc-400">
                            {typeof row.starter === 'boolean' ? (
                              row.starter ? (
                                <span className="inline-grid size-5 place-items-center rounded-full bg-[#ff5b24]/20 text-[#ff5b24]">
                                  <Check className="size-3 stroke-[3]" />
                                </span>
                              ) : (
                                <Minus className="inline-block size-4 text-zinc-600" />
                              )
                            ) : (
                              <span className="font-semibold text-zinc-200">{row.starter}</span>
                            )}
                          </td>
                          <td className="px-4 py-3.5 text-center text-zinc-400">
                            {typeof row.pro === 'boolean' ? (
                              row.pro ? (
                                <span className="inline-grid size-5 place-items-center rounded-full bg-[#ff5b24]/20 text-[#ff5b24]">
                                  <Check className="size-3 stroke-[3]" />
                                </span>
                              ) : (
                                <Minus className="inline-block size-4 text-zinc-600" />
                              )
                            ) : (
                              <span className="font-semibold text-[#ff7747]">{row.pro}</span>
                            )}
                          </td>
                          <td className="py-3.5 pl-4 pr-6 text-center text-zinc-400">
                            {typeof row.enterprise === 'boolean' ? (
                              row.enterprise ? (
                                <span className="inline-grid size-5 place-items-center rounded-full bg-[#ff5b24]/20 text-[#ff5b24]">
                                  <Check className="size-3 stroke-[3]" />
                                </span>
                              ) : (
                                <Minus className="inline-block size-4 text-zinc-600" />
                              )
                            ) : (
                              <span className="font-semibold text-white">{row.enterprise}</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </Reveal>

            {/* Bottom Support Callout */}
            <div className="mt-8 text-center text-xs text-zinc-400">
              <span>Looking for custom on-premise deployment or high-volume queries? </span>
              <a
                href="mailto:hello@openvault.site?subject=Deskwise%20custom%20enterprise"
                className="font-medium text-[#ff7747] underline hover:text-[#ff5b24]"
              >
                Contact our enterprise team →
              </a>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
export default PricingSection
