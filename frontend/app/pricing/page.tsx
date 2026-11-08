'use client'

import { SiteHeader } from '@/components/site-header'
import { SiteFooter } from '@/components/site-footer'
import { PricingSection } from '@/components/marketing/pricing-section'
import { FaqSection } from '@/components/marketing/faq-section'
import { FinalCta } from '@/components/marketing/final-cta'

export default function PricingPage() {
  return (
    <main id="main-content" className="min-h-screen bg-[#0a0a0c] text-white overflow-x-clip">
      <SiteHeader />
      <div className="pt-8">
        <PricingSection showTable={true} />
      </div>
      <FaqSection />
      <FinalCta />
      <SiteFooter />
    </main>
  )
}
