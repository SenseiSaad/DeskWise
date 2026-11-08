import { SiteHeader } from '@/components/site-header'
import { SiteFooter } from '@/components/site-footer'
import { PricingSection } from '@/components/marketing/pricing-section'
import { FaqSection } from '@/components/marketing/faq-section'
import { FinalCta } from '@/components/marketing/final-cta'

export default function PricingPage() {
  return (
    <main id="main-content" className="min-h-screen overflow-x-clip">
      <SiteHeader />
      <PricingSection showTable />
      <FaqSection />
      <FinalCta />
      <SiteFooter />
    </main>
  )
}
